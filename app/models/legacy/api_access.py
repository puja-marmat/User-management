"""Partner API access grants per site (Backend/GrantApiAccess).

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


class GrantApiAccess(LegacyBase):
    __tablename__ = "GrantApiAccesses"
    id: Mapped[int] = mapped_column("Id", Integer(), primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column("SiteId", Integer(), nullable=False)
    api_methods: Mapped[str | None] = mapped_column("ApiMethods", NVARCHAR(), nullable=True)
    white_listed_ip_addresses: Mapped[str | None] = mapped_column(
        "WhiteListedIPAddresses", NVARCHAR(), nullable=True
    )
    is_deleted: Mapped[bool] = mapped_column("IsDeleted", BIT(), nullable=False)
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


class HistoricalGrantApiAccess(LegacyBase):
    __tablename__ = "HistoricalGrantApiAccesses"
    id: Mapped[int] = mapped_column("Id", Integer(), primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column("SiteId", Integer(), nullable=False)
    api_methods: Mapped[str | None] = mapped_column("ApiMethods", NVARCHAR(), nullable=True)
    white_listed_ip_addresses: Mapped[str | None] = mapped_column(
        "WhiteListedIPAddresses", NVARCHAR(), nullable=True
    )
    is_deleted: Mapped[bool] = mapped_column("IsDeleted", BIT(), nullable=False)
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
