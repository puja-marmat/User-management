"""User change log and login log (101 §5.1).

Generated from the `sav_uat` schema script (2026-10-15) and checked by
`tests/test_legacy_models.py` (contract) and `tests/integration/test_legacy_schema.py`
(live INFORMATION_SCHEMA). Table and column names are the legacy names; never emit DDL
for these tables (they are outside Alembic's target metadata).
"""

from datetime import datetime
import uuid

from sqlalchemy import Integer
from sqlalchemy.dialects.mssql import DATETIME, NVARCHAR, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import LegacyBase


class ApplicationUserChangeLog(LegacyBase):
    __tablename__ = "ApplicationUserChangeLogs"
    id: Mapped[int] = mapped_column("Id", Integer(), primary_key=True, autoincrement=True)
    description: Mapped[str | None] = mapped_column("Description", NVARCHAR(), nullable=True)
    user_name: Mapped[str | None] = mapped_column("UserName", NVARCHAR(), nullable=True)
    application_user_id: Mapped[int] = mapped_column("ApplicationUserId", Integer(), nullable=False)
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


class LogUserLogin(LegacyBase):
    __tablename__ = "LogUserLogins"
    id: Mapped[int] = mapped_column("Id", Integer(), primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column("SiteId", Integer(), nullable=False)
    user_id: Mapped[int] = mapped_column("UserId", Integer(), nullable=False)
    user_name: Mapped[str | None] = mapped_column("UserName", NVARCHAR(100), nullable=True)
    full_name: Mapped[str | None] = mapped_column("FullName", NVARCHAR(100), nullable=True)
    web_request_identification: Mapped[str | None] = mapped_column(
        "WebRequestIdentification", NVARCHAR(500), nullable=True
    )
    ip: Mapped[str | None] = mapped_column("IP", NVARCHAR(50), nullable=True)
    created_date: Mapped[datetime] = mapped_column("CreatedDate", DATETIME(), nullable=False)
    email: Mapped[str | None] = mapped_column("Email", NVARCHAR(100), nullable=True)
