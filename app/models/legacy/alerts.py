"""Alert templates (read-only in U01): `Alerts` and `SiteAlerts`.

Read by the legacy `AlertHelper.Functions.AddAlertQueue` [Code
`CrystalPower.Web/Helpers/AlertHelpers/Functions.cs`] to build the Login and
ForgotPasswordOTP rows in `AlertQueues` (P1-M2). U01 never writes these tables.
Columns from the `sav_uat` schema script; checked by the same contract and live tests
as the other legacy models.
"""

from datetime import datetime
import uuid

from sqlalchemy import Integer
from sqlalchemy.dialects.mssql import BIT, DATETIME, NVARCHAR, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import LegacyBase


class Alert(LegacyBase):
    __tablename__ = "Alerts"
    id: Mapped[int] = mapped_column("Id", Integer(), primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column("Name", NVARCHAR(50), nullable=True)
    source_id: Mapped[int] = mapped_column("SourceId", Integer(), nullable=False)
    pattern_id: Mapped[int] = mapped_column("PatternId", Integer(), nullable=False)
    status_id: Mapped[int] = mapped_column("StatusId", Integer(), nullable=False)
    delivery_method_id: Mapped[int] = mapped_column("DeliveryMethodId", Integer(), nullable=False)
    message: Mapped[str | None] = mapped_column("Message", NVARCHAR(), nullable=True)
    subject: Mapped[str | None] = mapped_column("Subject", NVARCHAR(), nullable=True)
    editable_at_site_level: Mapped[bool] = mapped_column(
        "EditableAtSiteLevel", BIT(), nullable=False
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        "CreatedByUserId", Integer(), nullable=True
    )
    created_date: Mapped[datetime] = mapped_column("CreatedDate", DATETIME(), nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        "UpdatedByUserId", Integer(), nullable=True
    )
    updated_date: Mapped[datetime | None] = mapped_column("UpdatedDate", DATETIME(), nullable=True)
    guid: Mapped[uuid.UUID] = mapped_column(
        "Guid", UNIQUEIDENTIFIER(as_uuid=True), nullable=False, default=uuid.uuid4
    )


class SiteAlert(LegacyBase):
    __tablename__ = "SiteAlerts"
    id: Mapped[int] = mapped_column("Id", Integer(), primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column("SiteId", Integer(), nullable=False)
    alert_id: Mapped[int] = mapped_column("AlertId", Integer(), nullable=False)
    status_id: Mapped[int] = mapped_column("StatusId", Integer(), nullable=False)
    message: Mapped[str | None] = mapped_column("Message", NVARCHAR(), nullable=True)
    subject: Mapped[str | None] = mapped_column("Subject", NVARCHAR(), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        "CreatedByUserId", Integer(), nullable=True
    )
    created_date: Mapped[datetime] = mapped_column("CreatedDate", DATETIME(), nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        "UpdatedByUserId", Integer(), nullable=True
    )
    updated_date: Mapped[datetime | None] = mapped_column("UpdatedDate", DATETIME(), nullable=True)
    guid: Mapped[uuid.UUID] = mapped_column(
        "Guid", UNIQUEIDENTIFIER(as_uuid=True), nullable=False, default=uuid.uuid4
    )
