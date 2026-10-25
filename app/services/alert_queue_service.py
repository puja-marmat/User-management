"""
Login and ForgotPasswordOTP rows in `AlertQueues` — legacy `AddAlertQueue`
[Code `CrystalPower.Web/Helpers/AlertHelpers/Functions.cs:24-112`].

Legacy order, kept:
1. `alert = Alerts.FirstOrDefault(Name == <AlertEnum description>)`.
2. Only when `alert.StatusId == Enabled (1)`.
3. Site: given site, else the meter's site (`meter.SiteId <= 0` → current site).
4. `SiteAlerts` row for (alert Guid, site) with `Alerts.EditableAtSiteLevel = 1`;
   if it exists and is Disabled (0) → nothing queued.
5. `ToAddress` = e-mail when `DeliveryMethodId == Email (1)`, else phone (SMS = 0).
6. `Message` = `alert.Message` (not the site message). Login: skipped for end users and
   site admins; `{username}` replaced. ForgotPasswordOTP: `{OTP}` replaced.
7. Meter fields (`MeterNo`, `MeterStatusId`) when a meter is given.
8. `FromAddress` = appSetting `CustomerSupportEmail` → `ALERT_FROM_ADDRESS`;
   `CreatedByUserId` = the user; `CreatedDate` = India now; `DeliveryMethodId`, `PatternId`,
   `AlertId` from the alert; new `Guid`; `SiteId` = step 3; `DeliveryStatusId` = Pending (101);
   `IsSent` = false.
9. Inserted only when `ToAddress` is not empty.
Login and ForgotPasswordOTP are not in `EndUserAlerts`, so `ApplicationUserAlerts` is never
written (legacy step after 9).

Deviations (all where legacy would throw an exception):
* missing alert row, NULL message or missing `ALERT_FROM_ADDRESS` → nothing queued, warning
  logged with the reason only;
* ForgotPasswordOTP: legacy cp-web dereferences a null meter (NullReferenceException) so it
  never queues; approved fix (2026-10-23): site = the user's first `UserSites.SiteId`, and a
  user without a site gets `SiteId` NULL and no SiteAlert check.

Never log the message, address or OTP.
"""

from dataclasses import dataclass
from enum import IntEnum, StrEnum
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import Settings
from app.core.legacy_time import india_now
from app.models.legacy import Alert, AlertQueue, ApplicationUser, Meter, SiteAlert
from app.schemas.auth import Flags


log = structlog.get_logger(__name__)

STATUS_ENABLED = 1
STATUS_DISABLED = 0
DELIVERY_PENDING = 101


class DeliveryMethod(IntEnum):
    SMS = 0
    EMAIL = 1


class AlertName(StrEnum):
    """`AlertEnum` descriptions (the `Alerts.Name` values) [Code `Domain/Enums/AlertEnum.cs`]."""

    LOGIN = "Login"
    FORGOT_PASSWORD_OTP = "Forgot Password OTP"  # noqa: S105 - alert name


class QueueOutcome(StrEnum):
    QUEUED = "queued"
    ALERT_MISSING = "alert_missing"
    ALERT_DISABLED = "alert_disabled"
    SITE_ALERT_DISABLED = "site_alert_disabled"
    SKIPPED_FOR_ROLE = "skipped_for_role"
    NO_MESSAGE = "no_message"
    NO_FROM_ADDRESS = "no_from_address"
    NO_TO_ADDRESS = "no_to_address"


@dataclass(frozen=True)
class MeterRef:
    meter_no: str
    site_id: int
    status_id: int


async def find_meter(session: AsyncSession, site_id: int, meter_no: str) -> MeterRef | None:
    """`MeterRepository.GetByMeterNumberAndSiteId(siteId, meterNo)` → first row."""
    row = (
        await session.execute(
            select(Meter.meter_no, Meter.site_id, Meter.status_id)
            .where(Meter.site_id == site_id, Meter.meter_no == meter_no)
            .order_by(Meter.id)
            .limit(1)
        )
    ).first()
    return MeterRef(row.meter_no, row.site_id, row.status_id) if row else None


async def _site_alert_disabled(session: AsyncSession, alert: Alert, site_id: int) -> bool:
    status = (
        await session.execute(
            select(SiteAlert.status_id)
            .join(Alert, Alert.id == SiteAlert.alert_id)
            .where(
                Alert.editable_at_site_level.is_(True),
                SiteAlert.site_id == site_id,
                Alert.guid == alert.guid,
            )
            .order_by(SiteAlert.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    return status is not None and status == STATUS_DISABLED


async def _queue(
    session: AsyncSession,
    settings: Settings,
    user: ApplicationUser,
    name: AlertName,
    *,
    site_id: int | None,
    check_site_alert: bool,
    meter: MeterRef | None = None,
    skip: bool = False,
    replacements: dict[str, str] | None = None,
) -> QueueOutcome:
    alert = (
        await session.execute(
            select(Alert).where(Alert.name == name.value).order_by(Alert.id).limit(1)
        )
    ).scalar_one_or_none()
    if alert is None:
        return _warn(name, QueueOutcome.ALERT_MISSING)
    if alert.status_id != STATUS_ENABLED:
        return QueueOutcome.ALERT_DISABLED
    if (
        check_site_alert
        and site_id is not None
        and await _site_alert_disabled(session, alert, site_id)
    ):
        return QueueOutcome.SITE_ALERT_DISABLED
    to_address = (
        user.email if alert.delivery_method_id == DeliveryMethod.EMAIL else user.phone_number
    )
    if skip:
        return QueueOutcome.SKIPPED_FOR_ROLE
    if alert.message is None:
        return _warn(name, QueueOutcome.NO_MESSAGE)
    message = alert.message
    for placeholder, value in (replacements or {}).items():
        message = message.replace(placeholder, value)
    if not settings.ALERT_FROM_ADDRESS:
        return _warn(name, QueueOutcome.NO_FROM_ADDRESS)
    if not to_address:
        return QueueOutcome.NO_TO_ADDRESS
    session.add(
        AlertQueue(
            from_address=settings.ALERT_FROM_ADDRESS,
            to_address=to_address,
            message=message,
            delivery_method_id=alert.delivery_method_id,
            pattern_id=alert.pattern_id,
            is_sent=False,
            delivery_status_id=DELIVERY_PENDING,
            meter_status_id=meter.status_id if meter else None,
            alert_id=alert.id,
            site_id=site_id,
            meter_no=meter.meter_no if meter else None,
            created_by_user_id=user.id,
            created_date=india_now(),
            guid=uuid.uuid4(),
        )
    )
    return QueueOutcome.QUEUED


def _warn(name: AlertName, outcome: QueueOutcome) -> QueueOutcome:
    log.warning("alert_not_queued", alert=name.value, reason=outcome.value)
    return outcome


async def queue_login_alert(
    session: AsyncSession,
    settings: Settings,
    user: ApplicationUser,
    flags: Flags,
    meter: MeterRef,
    current_site_id: int,
) -> QueueOutcome:
    site_id = current_site_id if meter.site_id <= 0 else meter.site_id
    return await _queue(
        session,
        settings,
        user,
        AlertName.LOGIN,
        site_id=site_id,
        check_site_alert=True,
        meter=meter,
        skip=flags.is_end_user or flags.is_site_admin,
        replacements={"{username}": user.user_name or ""},
    )


async def queue_forgot_password_otp(
    session: AsyncSession,
    settings: Settings,
    user: ApplicationUser,
    otp: str,
    site_id: int | None,
) -> QueueOutcome:
    return await _queue(
        session,
        settings,
        user,
        AlertName.FORGOT_PASSWORD_OTP,
        site_id=site_id,
        check_site_alert=site_id is not None,
        replacements={"{OTP}": otp} if otp else None,
    )
