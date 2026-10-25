"""
Test database for P1-M2 unit tests: the legacy models on a temporary SQLite file
(schema `dbo` attached as a second file). No SQL Server, no real data — every row here
is synthetic. SQL Server specifics (collation, identity) are covered by the integration
tests on `sav_uat`.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import uuid

from sqlalchemy import event, inspect as sa_inspect
from sqlalchemy.dialects.mssql import BIT, TINYINT, UNIQUEIDENTIFIER
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import NullPool

from app.core.identity_password import hash_password
from app.models.base import LegacyBase
from app.models.legacy import (
    Alert,
    ApplicationRole,
    ApplicationRoleGroup,
    ApplicationRoleInGroup,
    ApplicationUser,
    ApplicationUserInGroup,
    Meter,
    Site,
    SiteAlert,
    Tower,
    UserSite,
)


@compiles(BIT, "sqlite")
def _bit(_type, _compiler, **_kw) -> str:
    return "BOOLEAN"


@compiles(TINYINT, "sqlite")
def _tinyint(_type, _compiler, **_kw) -> str:
    return "INTEGER"


@compiles(UNIQUEIDENTIFIER, "sqlite")
def _uuid(_type, _compiler, **_kw) -> str:
    return "CHAR(36)"


# Synthetic test password (meets the legacy policy); not a real credential.
GOOD_PASSWORD = "Test@1234"
NOW = datetime(2026, 10, 23, 10, 0, 0)


async def make_engine(tmp_path: Path) -> AsyncEngine:
    main_db = tmp_path / "main.db"
    dbo_db = tmp_path / "dbo.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{main_db}", poolclass=NullPool)

    @event.listens_for(engine.sync_engine, "connect")
    def _attach(dbapi_conn, _record) -> None:
        dbapi_conn.execute(f"ATTACH DATABASE '{dbo_db}' AS dbo")

    async with engine.begin() as conn:
        await conn.run_sync(LegacyBase.metadata.create_all)
    return engine


def session_dependency(engine: AsyncEngine):
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    async def _dep() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    return _dep, factory


@dataclass
class Seed:
    admin_id: int
    end_user_id: int
    site_admin_id: int
    no_site_id: int
    super_id: int
    site_a: int
    site_b: int
    login_alert_id: int
    otp_alert_id: int


def user(**overrides) -> ApplicationUser:
    values = {
        "full_name": "Synthetic User",
        "status_id": 1,
        "guid": uuid.uuid4(),
        "created_date": NOW,
        "email": "synthetic@example.test",
        "email_confirmed": True,
        "password_hash": hash_password(GOOD_PASSWORD),
        "security_stamp": str(uuid.uuid4()),
        "phone_number": "9000000001",
        "phone_number_confirmed": False,
        "two_factor_enabled": False,
        "lockout_enabled": True,
        "access_failed_count": 0,
        "user_name": "synthetic.admin",
    }
    values.update(overrides)
    return ApplicationUser(**values)


def _group(name: str, site_id: int, **flags) -> ApplicationRoleGroup:
    values = {
        "name": name,
        "site_id": site_id,
        "is_site_admin": False,
        "is_super_admin": False,
        "is_editable": True,
        "is_end_user": False,
        "is_system_admin": False,
        "is_sub_division": False,
        "created_date": NOW,
    }
    values.update(flags)
    return ApplicationRoleGroup(**values)


async def seed(factory: async_sessionmaker[AsyncSession]) -> Seed:
    async with factory() as s:
        site_b = _site("Zeta Towers")
        site_a = _site("Alpha Heights")
        s.add_all([site_b, site_a])
        await s.flush()

        roles = [ApplicationRole(name=n) for n in ("View User", "Save User", "Meter List")]
        s.add_all(roles)
        g_admin = _group("Admins", site_a.id)
        g_end = _group("End users", site_a.id, is_end_user=True)
        g_site = _group("Site admins", site_a.id, is_site_admin=True)
        g_super = _group("Super", site_a.id, is_super_admin=True)
        g_sub = _group("Sub division", site_a.id, is_sub_division=True)
        s.add_all([g_admin, g_end, g_site, g_super, g_sub])
        await s.flush()
        for role in roles[:2]:
            s.add(
                ApplicationRoleInGroup(
                    application_role_group_id=g_admin.id, application_role_id=role.id
                )
            )
        s.add(
            ApplicationRoleInGroup(
                application_role_group_id=g_end.id, application_role_id=roles[2].id
            )
        )

        admin = user()
        end_user = user(user_name="synthetic.enduser", email="enduser@example.test")
        site_admin = user(user_name="synthetic.siteadmin", email="siteadmin@example.test")
        no_site = user(user_name="synthetic.nosite", email="nosite@example.test")
        super_user = user(user_name="synthetic.super", email="super@example.test")
        s.add_all([admin, end_user, site_admin, no_site, super_user])
        await s.flush()
        for u, g in (
            (admin, g_admin),
            (end_user, g_end),
            (site_admin, g_site),
            (super_user, g_super),
        ):
            s.add(ApplicationUserInGroup(application_role_group_id=g.id, application_user_id=u.id))
        # admin: two sites, first assignment = site B (lowest UserSites.Id)
        s.add(
            UserSite(
                application_user_id=admin.id, site_id=site_b.id, guid=uuid.uuid4(), created_date=NOW
            )
        )
        s.add(
            UserSite(
                application_user_id=admin.id, site_id=site_a.id, guid=uuid.uuid4(), created_date=NOW
            )
        )
        for u in (end_user, site_admin):
            s.add(
                UserSite(
                    application_user_id=u.id, site_id=site_a.id, guid=uuid.uuid4(), created_date=NOW
                )
            )

        login_alert = _alert("Login", "Crystal Power: {username} logged in", delivery=0)
        otp_alert = _alert("Forgot Password OTP", "Your OTP is {OTP}", delivery=0)
        s.add_all([login_alert, otp_alert])
        s.add(_meter("MTR000001", site_b.id))
        s.add(_meter("MTR000002", site_a.id))
        await s.commit()
        return Seed(
            admin_id=admin.id,
            end_user_id=end_user.id,
            site_admin_id=site_admin.id,
            no_site_id=no_site.id,
            super_id=super_user.id,
            site_a=site_a.id,
            site_b=site_b.id,
            login_alert_id=login_alert.id,
            otp_alert_id=otp_alert.id,
        )


async def add_sub_division_user(factory, site_id: int) -> int:
    async with factory() as s:
        g = _group("Sub division 2", site_id, is_sub_division=True)
        u = user(user_name="synthetic.subdiv", email="subdiv@example.test")
        s.add_all([g, u])
        await s.flush()
        s.add(ApplicationUserInGroup(application_role_group_id=g.id, application_user_id=u.id))
        s.add(
            UserSite(application_user_id=u.id, site_id=site_id, guid=uuid.uuid4(), created_date=NOW)
        )
        s.add(Tower(**_tower_values(site_id, u.id)))
        await s.commit()
        return u.id


async def set_site_alert(factory, alert_id: int, site_id: int, status: int, editable: bool = True):
    async with factory() as s:
        alert = await s.get(Alert, alert_id)
        alert.editable_at_site_level = editable
        s.add(
            SiteAlert(
                site_id=site_id,
                alert_id=alert_id,
                status_id=status,
                created_date=NOW,
                guid=uuid.uuid4(),
            )
        )
        await s.commit()


def _site(name: str) -> Site:
    values = _required_defaults(Site)
    values["name"] = name
    return Site(**values)


def _meter(meter_no: str, site_id: int) -> Meter:
    values = _required_defaults(Meter)
    values.update(meter_no=meter_no, site_id=site_id, status_id=1)
    return Meter(**values)


def _tower_values(site_id: int, user_id: int) -> dict:
    values = _required_defaults(Tower)
    values.update(site_id=site_id, user_id=user_id, name="Tower 1")
    return values


def _alert(name: str, message: str, delivery: int) -> Alert:
    return Alert(
        name=name,
        source_id=1,
        pattern_id=1,
        status_id=1,
        delivery_method_id=delivery,
        message=message,
        editable_at_site_level=False,
        created_date=NOW,
        guid=uuid.uuid4(),
    )


def _required_defaults(model) -> dict:
    values = {}
    for attr in sa_inspect(model).column_attrs:
        col = attr.columns[0]
        if not (col.primary_key or col.nullable):
            values[attr.key] = _default_for(col)
    return values


def _default_for(col):
    from sqlalchemy.dialects.mssql import DATETIME, DECIMAL, NVARCHAR

    t = col.type
    if isinstance(t, UNIQUEIDENTIFIER):
        return uuid.uuid4()
    if isinstance(t, BIT):
        return False
    if isinstance(t, DATETIME):
        return NOW
    if isinstance(t, NVARCHAR):
        return "x"
    if isinstance(t, DECIMAL):
        return 0
    return 0
