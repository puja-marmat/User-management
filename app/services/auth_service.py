"""
Login, token refresh and logout (01d A1-A3).

Legacy source [Code `CrystalPower.Web/Controllers/AccountController.cs`]:

Login POST (:150-205), in this order:
1. Validation: `Email` and `Password` required ("The Email field is required.").
2. `user = FindByName(x) ?? FindByEmail(x)`; none → "Invalid login attempt.".
3. **`UpdateSecurityStampAsync(user)`** — before any other check, even for a wrong
   password (kept, D1 default (a); it signs the user out of cp-web within 30 min and the
   reverse — legacy behaviour).
4. `StatusId == Disabled (0)` → "Your account is not enabled. Please contact administrator.".
5. `PasswordSignInAsync(..., shouldLockout: false)` [Identity 2.1 SignInManager]:
   locked out (`LockoutEnabled` and `LockoutEndDateUtc >= now UTC`) → Lockout view;
   wrong password → "Invalid login attempt." (`AccessFailedCount` untouched, F5 kept);
   right password → `AccessFailedCount` reset to 0 (no write when already 0);
   `TwoFactorEnabled` with a confirmed phone/e-mail → RequiresVerification (not supported
   in Phase 1: refused with TWO_FACTOR_NOT_SUPPORTED).
6. `ProcessLoginAlert` (:207-288): current site (`GetSiteIdOfLoginUser`), one
   `LogUserLogins` row, and when `meterNo` is given and the meter exists on that site, the
   Login alert (D5). The site-admin meter cookie / redirect and the sub-division tower
   cookie are UI concerns (meter module, P1-M3 towers) and are not ported here.
   A user without a current site crashes legacy at `.Value`; here login is refused before
   any token is issued (decision (c)).

Tables: R ApplicationUsers, role groups, UserSites, Sites, Towers, Meters, Alerts,
SiteAlerts · W ApplicationUsers (SecurityStamp, AccessFailedCount), LogUserLogins,
AlertQueues.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import Settings
from app.core.exceptions import CredentialsError, ForbiddenError
from app.core.identity_password import new_security_stamp, verify_password
from app.core.legacy_time import india_now
from app.core.security import AuthRuntime, Principal
from app.core.session_registry import RefreshOutcome
from app.models.legacy import ApplicationUser, LogUserLogin
from app.schemas.auth import LoginRequest, LoginResponse, TokenPair
from app.services.alert_queue_service import find_meter, queue_login_alert
from app.services.legacy_validation import FieldErrors
from app.services.profile import to_me_response
from app.services.user_context import build_user_context, find_user_by_email, find_user_by_name


log = structlog.get_logger(__name__)

INVALID_LOGIN = "Invalid login attempt."
NOT_ENABLED = "Your account is not enabled. Please contact administrator."
LOCKED_OUT = "Locked out. This account has been locked out, please try again later."
NO_SITE = "No site is assigned to your account. Please contact administrator."
TWO_FACTOR = "Two-factor sign-in is not available in this version. Please contact administrator."
SESSION_ENDED = "Session ended. Please log in again."
STATUS_DISABLED = 0


@dataclass(frozen=True)
class RequestMeta:
    ip: str
    web_request_identification: str


def is_locked_out(user: ApplicationUser, now_utc: datetime | None = None) -> bool:
    if not user.lockout_enabled or user.lockout_end_date_utc is None:
        return False
    now = (now_utc or datetime.now(UTC)).replace(tzinfo=None)
    return user.lockout_end_date_utc >= now


def requires_two_factor(user: ApplicationUser) -> bool:
    phone_ok = bool(user.phone_number) and user.phone_number_confirmed
    email_ok = bool(user.email) and user.email_confirmed
    return bool(user.two_factor_enabled) and (phone_ok or email_ok)


async def login(
    session: AsyncSession,
    settings: Settings,
    runtime: AuthRuntime,
    body: LoginRequest,
    meta: RequestMeta,
) -> LoginResponse:
    errors = FieldErrors()
    errors.required("userName", "Email", body.user_name)
    errors.required("password", "Password", body.password)
    errors.raise_if_any()

    user = await find_user_by_name(session, body.user_name) or await find_user_by_email(
        session, body.user_name
    )
    if user is None:
        log.info("login_failed", reason="unknown_user")
        raise CredentialsError(INVALID_LOGIN, error_code="INVALID_LOGIN")

    user.security_stamp = new_security_stamp()
    await session.commit()

    if user.status_id == STATUS_DISABLED:
        log.info("login_failed", reason="disabled", user_id=user.id)
        raise ForbiddenError(NOT_ENABLED, error_code="ACCOUNT_DISABLED")
    if is_locked_out(user):
        log.info("login_failed", reason="locked_out", user_id=user.id)
        raise ForbiddenError(LOCKED_OUT, error_code="ACCOUNT_LOCKED")
    if not verify_password(user.password_hash, body.password):
        log.info("login_failed", reason="bad_password", user_id=user.id)
        raise CredentialsError(INVALID_LOGIN, error_code="INVALID_LOGIN")
    if not user.two_factor_enabled and user.access_failed_count != 0:
        user.access_failed_count = 0
        await session.commit()
    if requires_two_factor(user):
        log.info("login_failed", reason="two_factor", user_id=user.id)
        raise ForbiddenError(TWO_FACTOR, error_code="TWO_FACTOR_NOT_SUPPORTED")

    ctx = await build_user_context(session, user)
    if ctx.default_site_id is None:
        log.info("login_failed", reason="no_site", user_id=user.id)
        raise ForbiddenError(NO_SITE, error_code="NO_SITE_ASSIGNED")

    session.add(
        LogUserLogin(
            full_name=user.full_name,
            user_id=user.id,
            email=user.email,
            user_name=user.user_name,
            created_date=india_now(),
            ip=meta.ip,
            web_request_identification=meta.web_request_identification,
            site_id=ctx.default_site_id,
        )
    )
    alert_outcome = None
    if body.meter_no:  # legacy: !string.IsNullOrEmpty(meterNo)
        meter = await find_meter(session, ctx.default_site_id, body.meter_no)
        if meter is not None:
            alert_outcome = await queue_login_alert(
                session, settings, user, ctx.flags, meter, ctx.default_site_id
            )
    await session.commit()

    tokens = issue_tokens(runtime, user, body.remember_me)
    log.info(
        "login_succeeded",
        user_id=user.id,
        remember_me=body.remember_me,
        login_alert=alert_outcome.value if alert_outcome else None,
    )
    me = to_me_response(ctx, ctx.default_site_id)
    return LoginResponse(**me.model_dump(), **tokens.model_dump())


def issue_tokens(runtime: AuthRuntime, user: ApplicationUser, remember_me: bool) -> TokenPair:
    refresh = runtime.sessions.create(
        user.id, remember_me, runtime.tokens.stamp_fingerprint(user.security_stamp)
    )
    access, expires = runtime.tokens.create_access_token(user.id, refresh.session_id)
    return TokenPair(
        access_token=access,
        expires_at=expires,
        refresh_token=refresh.refresh_token,
        refresh_expires_at=refresh.expires_at.replace(microsecond=0),
        remember_me=remember_me,
    )


_REFRESH_ERRORS = {
    RefreshOutcome.INVALID: "REFRESH_TOKEN_INVALID",
    RefreshOutcome.EXPIRED: "REFRESH_TOKEN_EXPIRED",
    RefreshOutcome.REVOKED: "SESSION_ENDED",
    RefreshOutcome.REPLAYED: "REFRESH_TOKEN_REUSED",
}


async def refresh(
    session: AsyncSession, runtime: AuthRuntime, refresh_token: str | None
) -> TokenPair:
    outcome, sess, issued = runtime.sessions.rotate(refresh_token)
    if outcome is not RefreshOutcome.OK or sess is None or issued is None:
        if outcome is RefreshOutcome.REPLAYED:
            log.warning("refresh_token_replayed", user_id=sess.user_id if sess else None)
        raise CredentialsError(SESSION_ENDED, error_code=_REFRESH_ERRORS[outcome])

    user = await session.get(ApplicationUser, sess.user_id)
    fingerprint = runtime.tokens.stamp_fingerprint(user.security_stamp) if user else None
    if user is None or fingerprint != sess.stamp_fingerprint:
        # Legacy SecurityStampValidator: stamp changed (login elsewhere, password change or
        # reset) → the session is rejected.
        runtime.sessions.revoke(sess.session_id)
        raise CredentialsError(SESSION_ENDED, error_code="SESSION_ENDED")

    access, expires = runtime.tokens.create_access_token(user.id, sess.session_id)
    return TokenPair(
        access_token=access,
        expires_at=expires,
        refresh_token=issued.refresh_token,
        refresh_expires_at=issued.expires_at.replace(microsecond=0),
        remember_me=sess.remember_me,
    )


def logout(runtime: AuthRuntime, principal: Principal) -> None:
    """Legacy LogOff only clears the cookie (stamp unchanged); here the session is revoked."""
    runtime.sessions.revoke(principal.session_id)
    log.info("logout", user_id=principal.user_id)
