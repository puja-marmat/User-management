"""
Which legacy tables the U01 parity harness reads, how rows are selected, and which
columns are personal (hashed) or volatile (ignored when comparing two applications).

Scope = the tables U01 *writes* (01a §P1). Reference tables (`Sites`, `Towers`, `Meters`)
and `ApplicationRoles` are read-only in U01 and are not snapshotted.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Table

from app.models.legacy import (
    AlertQueue,
    ApplicationRoleGroup,
    ApplicationRoleInGroup,
    ApplicationUser,
    ApplicationUserChangeLog,
    ApplicationUserInGroup,
    BroadcastMessage,
    GrantApiAccess,
    HistoricalGrantApiAccess,
    LogUserLogin,
    UserSite,
)


SelectBy = Literal["user", "role_group", "site", "site_or_all"]


@dataclass(frozen=True)
class TableSpec:
    name: str
    table: Table
    filter_column: str  # column compared with the selected ids
    select_by: SelectBy
    append_only: bool  # rows are only inserted: captured as "new since baseline"
    personal: frozenset[str]  # HMAC-hashed in snapshots, never printed
    volatile: frozenset[str]  # ignored by `compare` (ids, guids, clocks, secrets, OTP text)
    user_ref: frozenset[str]  # columns holding ApplicationUsers.Id (subject substitution)


_COMMON_VOLATILE = frozenset({"Id", "Guid", "CreatedDate", "UpdatedDate"})
_AUDIT_USERS = frozenset({"CreatedByUserId", "UpdatedByUserId"})

PARITY_TABLES: tuple[TableSpec, ...] = (
    TableSpec(
        "ApplicationUsers",
        ApplicationUser.__table__,
        "Id",
        "user",
        False,
        frozenset(
            {
                "FullName",
                "ConsumerNo",
                "ShareBillsWith",
                "Email",
                "PasswordHash",
                "SecurityStamp",
                "PhoneNumber",
                "UserName",
            }
        ),
        _COMMON_VOLATILE | {"PasswordHash", "SecurityStamp", "LockoutEndDateUtc"},
        frozenset({"Id"}) | _AUDIT_USERS,
    ),
    TableSpec(
        "ApplicationUsersInGroups",
        ApplicationUserInGroup.__table__,
        "ApplicationUserId",
        "user",
        False,
        frozenset(),
        _COMMON_VOLATILE,
        frozenset({"ApplicationUserId"}),
    ),
    TableSpec(
        "UserSites",
        UserSite.__table__,
        "ApplicationUserId",
        "user",
        False,
        frozenset(),
        _COMMON_VOLATILE,
        frozenset({"ApplicationUserId"}) | _AUDIT_USERS,
    ),
    TableSpec(
        "ApplicationUserChangeLogs",
        ApplicationUserChangeLog.__table__,
        "ApplicationUserId",
        "user",
        True,
        frozenset({"Description", "UserName"}),
        _COMMON_VOLATILE,
        frozenset({"ApplicationUserId"}) | _AUDIT_USERS,
    ),
    TableSpec(
        "LogUserLogins",
        LogUserLogin.__table__,
        "UserId",
        "user",
        True,
        frozenset({"UserName", "FullName", "WebRequestIdentification", "IP", "Email"}),
        _COMMON_VOLATILE | {"WebRequestIdentification", "IP"},
        frozenset({"UserId"}),
    ),
    TableSpec(
        "ApplicationRoleGroups",
        ApplicationRoleGroup.__table__,
        "Id",
        "role_group",
        False,
        frozenset(),
        _COMMON_VOLATILE,
        _AUDIT_USERS,
    ),
    TableSpec(
        "ApplicationRolesInGroups",
        ApplicationRoleInGroup.__table__,
        "ApplicationRoleGroupId",
        "role_group",
        False,
        frozenset(),
        _COMMON_VOLATILE | {"ApplicationRoleGroupId"},
        frozenset(),
    ),
    TableSpec(
        "GrantApiAccesses",
        GrantApiAccess.__table__,
        "SiteId",
        "site",
        False,
        frozenset({"WhiteListedIPAddresses"}),
        _COMMON_VOLATILE,
        _AUDIT_USERS,
    ),
    TableSpec(
        "HistoricalGrantApiAccesses",
        HistoricalGrantApiAccess.__table__,
        "SiteId",
        "site",
        True,
        frozenset({"WhiteListedIPAddresses"}),
        _COMMON_VOLATILE,
        _AUDIT_USERS,
    ),
    TableSpec(
        "AlertQueues",
        AlertQueue.__table__,
        "SiteId",
        "site_or_all",
        True,
        frozenset(
            {
                "FromAddress",
                "ToAddress",
                "CCAddress",
                "BCCAddress",
                "Subject",
                "Message",
                "ErrorMessage",
                "MeterNo",
            }
        ),
        # Message carries OTPs / passwords and differs on every run.
        _COMMON_VOLATILE | {"Message", "SentOn"},
        _AUDIT_USERS,
    ),
    TableSpec(
        "BroadcastMessages",
        BroadcastMessage.__table__,
        "SiteId",
        "site_or_all",
        True,
        frozenset({"Message"}),
        _COMMON_VOLATILE | {"ProcessedOn"},
        _AUDIT_USERS,
    ),
)

TABLES_BY_NAME = {t.name: t for t in PARITY_TABLES}
