"""Identity, role groups, permissions and site membership (cp-web User Management, 101 §5.1).

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


class ApplicationUser(LegacyBase):
    __tablename__ = "ApplicationUsers"
    id: Mapped[int] = mapped_column("Id", Integer(), primary_key=True, autoincrement=True)
    full_name: Mapped[str | None] = mapped_column("FullName", NVARCHAR(100), nullable=True)
    status_id: Mapped[int] = mapped_column("StatusId", Integer(), nullable=False)
    consumer_no: Mapped[str | None] = mapped_column("ConsumerNo", NVARCHAR(), nullable=True)
    guid: Mapped[uuid.UUID] = mapped_column(
        "Guid", UNIQUEIDENTIFIER(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        "CreatedByUserId", Integer(), nullable=True
    )
    created_date: Mapped[datetime] = mapped_column("CreatedDate", DATETIME(), nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        "UpdatedByUserId", Integer(), nullable=True
    )
    updated_date: Mapped[datetime | None] = mapped_column("UpdatedDate", DATETIME(), nullable=True)
    last_read_news_id: Mapped[int | None] = mapped_column(
        "LastReadNewsId", Integer(), nullable=True
    )
    last_read_admin_alert_id: Mapped[int | None] = mapped_column(
        "LastReadAdminAlertId", Integer(), nullable=True
    )
    last_read_user_alert_id: Mapped[int | None] = mapped_column(
        "LastReadUserAlertId", Integer(), nullable=True
    )
    share_bills_with: Mapped[str | None] = mapped_column(
        "ShareBillsWith", NVARCHAR(), nullable=True
    )
    email: Mapped[str | None] = mapped_column("Email", NVARCHAR(), nullable=True)
    email_confirmed: Mapped[bool] = mapped_column("EmailConfirmed", BIT(), nullable=False)
    password_hash: Mapped[str | None] = mapped_column("PasswordHash", NVARCHAR(), nullable=True)
    security_stamp: Mapped[str | None] = mapped_column("SecurityStamp", NVARCHAR(), nullable=True)
    phone_number: Mapped[str | None] = mapped_column("PhoneNumber", NVARCHAR(), nullable=True)
    phone_number_confirmed: Mapped[bool] = mapped_column(
        "PhoneNumberConfirmed", BIT(), nullable=False
    )
    two_factor_enabled: Mapped[bool] = mapped_column("TwoFactorEnabled", BIT(), nullable=False)
    lockout_end_date_utc: Mapped[datetime | None] = mapped_column(
        "LockoutEndDateUtc", DATETIME(), nullable=True
    )
    lockout_enabled: Mapped[bool] = mapped_column("LockoutEnabled", BIT(), nullable=False)
    access_failed_count: Mapped[int] = mapped_column("AccessFailedCount", Integer(), nullable=False)
    user_name: Mapped[str | None] = mapped_column("UserName", NVARCHAR(), nullable=True)


class ApplicationRole(LegacyBase):
    __tablename__ = "ApplicationRoles"
    id: Mapped[int] = mapped_column("Id", Integer(), primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column("Name", NVARCHAR(), nullable=True)


class ApplicationRoleGroup(LegacyBase):
    __tablename__ = "ApplicationRoleGroups"
    id: Mapped[int] = mapped_column("Id", Integer(), primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column("Name", NVARCHAR(50), nullable=True)
    site_id: Mapped[int] = mapped_column("SiteId", Integer(), nullable=False)
    is_site_admin: Mapped[bool] = mapped_column("IsSiteAdmin", BIT(), nullable=False)
    is_super_admin: Mapped[bool] = mapped_column("IsSuperAdmin", BIT(), nullable=False)
    is_editable: Mapped[bool] = mapped_column("IsEditable", BIT(), nullable=False)
    is_end_user: Mapped[bool] = mapped_column("IsEndUser", BIT(), nullable=False)
    is_system_admin: Mapped[bool] = mapped_column("IsSystemAdmin", BIT(), nullable=False)
    is_sub_division: Mapped[bool] = mapped_column("IsSubDivision", BIT(), nullable=False)
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


class ApplicationRoleInGroup(LegacyBase):
    __tablename__ = "ApplicationRolesInGroups"
    id: Mapped[int] = mapped_column("Id", Integer(), primary_key=True, autoincrement=True)
    application_role_group_id: Mapped[int] = mapped_column(
        "ApplicationRoleGroupId", Integer(), nullable=False
    )
    application_role_id: Mapped[int] = mapped_column("ApplicationRoleId", Integer(), nullable=False)
    guid: Mapped[uuid.UUID] = mapped_column(
        "Guid", UNIQUEIDENTIFIER(as_uuid=True), nullable=False, default=uuid.uuid4
    )


class ApplicationUserInGroup(LegacyBase):
    __tablename__ = "ApplicationUsersInGroups"
    id: Mapped[int] = mapped_column("Id", Integer(), primary_key=True, autoincrement=True)
    application_role_group_id: Mapped[int] = mapped_column(
        "ApplicationRoleGroupId", Integer(), nullable=False
    )
    application_user_id: Mapped[int] = mapped_column("ApplicationUserId", Integer(), nullable=False)
    guid: Mapped[uuid.UUID] = mapped_column(
        "Guid", UNIQUEIDENTIFIER(as_uuid=True), nullable=False, default=uuid.uuid4
    )


class UserSite(LegacyBase):
    __tablename__ = "UserSites"
    id: Mapped[int] = mapped_column("Id", Integer(), primary_key=True, autoincrement=True)
    application_user_id: Mapped[int] = mapped_column("ApplicationUserId", Integer(), nullable=False)
    site_id: Mapped[int] = mapped_column("SiteId", Integer(), nullable=False)
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
