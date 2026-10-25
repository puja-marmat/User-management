"""Outbound message queue rows written by User Management (OTP, login alert, credentials, broadcast).

Generated from the `sav_uat` schema script (2026-10-15) and checked by
`tests/test_legacy_models.py` (contract) and `tests/integration/test_legacy_schema.py`
(live INFORMATION_SCHEMA). Table and column names are the legacy names; never emit DDL
for these tables (they are outside Alembic's target metadata).
"""

from datetime import datetime
import uuid

from sqlalchemy import Integer
from sqlalchemy.dialects.mssql import BIT, DATETIME, NVARCHAR, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import LegacyBase


class AlertQueue(LegacyBase):
    __tablename__ = "AlertQueues"
    id: Mapped[int] = mapped_column("Id", Integer(), primary_key=True, autoincrement=True)
    from_address: Mapped[str] = mapped_column("FromAddress", NVARCHAR(500), nullable=False)
    to_address: Mapped[str | None] = mapped_column("ToAddress", NVARCHAR(500), nullable=True)
    cc_address: Mapped[str | None] = mapped_column("CCAddress", NVARCHAR(500), nullable=True)
    bcc_address: Mapped[str | None] = mapped_column("BCCAddress", NVARCHAR(500), nullable=True)
    subject: Mapped[str | None] = mapped_column("Subject", NVARCHAR(500), nullable=True)
    message: Mapped[str] = mapped_column("Message", NVARCHAR(), nullable=False)
    error_message: Mapped[str | None] = mapped_column("ErrorMessage", NVARCHAR(), nullable=True)
    delivery_method_id: Mapped[int] = mapped_column("DeliveryMethodId", Integer(), nullable=False)
    pattern_id: Mapped[int] = mapped_column("PatternId", Integer(), nullable=False)
    is_sent: Mapped[bool] = mapped_column("IsSent", BIT(), nullable=False)
    sent_on: Mapped[datetime | None] = mapped_column("SentOn", DATETIME(), nullable=True)
    delivery_status_id: Mapped[int | None] = mapped_column(
        "DeliveryStatusId", Integer(), nullable=True
    )
    meter_status_id: Mapped[int | None] = mapped_column("MeterStatusId", Integer(), nullable=True)
    alert_id: Mapped[int | None] = mapped_column("AlertId", Integer(), nullable=True)
    site_id: Mapped[int | None] = mapped_column("SiteId", Integer(), nullable=True)
    email_type_id: Mapped[int | None] = mapped_column("EmailTypeId", Integer(), nullable=True)
    meter_no: Mapped[str | None] = mapped_column("MeterNo", NVARCHAR(), nullable=True)
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


class BroadcastMessage(LegacyBase):
    __tablename__ = "BroadcastMessages"
    id: Mapped[int] = mapped_column("Id", Integer(), primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column("SiteId", Integer(), nullable=False)
    message: Mapped[str | None] = mapped_column("Message", NVARCHAR(), nullable=True)
    delivery_method_id: Mapped[int] = mapped_column("DeliveryMethodId", Integer(), nullable=False)
    is_processed: Mapped[bool] = mapped_column("IsProcessed", BIT(), nullable=False)
    processed_on: Mapped[datetime | None] = mapped_column("ProcessedOn", DATETIME(), nullable=True)
    except_end_users_send_to_all: Mapped[bool] = mapped_column(
        "ExceptEndUsersSendToAll", BIT(), nullable=False
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
