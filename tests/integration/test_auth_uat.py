"""
P1-M2 against `sav_uat` with the synthetic user created in UAT cp-web (marker: integration).

Needs, in the PowerShell session only (never in a file, never in chat):

    $env:UAT_TEST_USERNAME = "<synthetic user name>"
    $env:UAT_SYNTHETIC_ACCOUNT_CONFIRM = "<the same name again>"   # must match exactly
    $env:UAT_TEST_PASSWORD = "<its password>"          # typed by you, see docs/UAT-P1-M2.md
    $env:UAT_ALLOW_PASSWORD_WRITE = "1"                # optional: A6/A9 round trips

What it writes (synthetic user only): ApplicationUsers.SecurityStamp (every login, as
legacy), LogUserLogins (one row per successful login), AlertQueues (forgot-password OTP;
nothing sends it on UAT, D2). With UAT_ALLOW_PASSWORD_WRITE=1 it also re-sets the SAME
password through reset (A9) and change-password (A6), producing new Identity v2 hashes —
the password you know keeps working. Every other U01 table is checked unchanged.

The OTP is read from AlertQueues inside the test (D4) and never printed.

Every test here writes account data, so before the first one the module fixture
`_synthetic_account_only` runs `tests/integration/account_guard.py` (after the session
`sav_uat` guard): confirmation must match, exactly one account must match the name, it must
not be in a Super Admin or System Admin group, and any read error refuses (exit code 4).
Assertions compare hashes and stamps as booleans so a failure never prints them.
"""

import os
import re

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import text

from app.core.config import get_settings
from tests.integration.account_guard import enforce_synthetic_account


pytestmark = pytest.mark.integration

USER = os.environ.get("UAT_TEST_USERNAME")
PASSWORD = os.environ.get("UAT_TEST_PASSWORD")
ALLOW_WRITE = os.environ.get("UAT_ALLOW_PASSWORD_WRITE") == "1"

UNCHANGED_TABLES = (
    "ApplicationRoles",
    "ApplicationRoleGroups",
    "ApplicationRolesInGroups",
    "ApplicationUsersInGroups",
    "UserSites",
    "Towers",
    "ApplicationUserChangeLogs",
    "BroadcastMessages",
    "GrantApiAccesses",
    "HistoricalGrantApiAccesses",
    "Sites",
    "Meters",
    "Alerts",
    "SiteAlerts",
)


@pytest.fixture(scope="module", autouse=True)
def _synthetic_account_only() -> None:
    """Runs once before the first test of this module; every test here writes account data."""
    if get_settings().DB_WRITER_URL is None or not USER or not PASSWORD:
        return  # the tests skip themselves (see `uat`)
    enforce_synthetic_account(os.environ)


@pytest.fixture
async def uat():
    if get_settings().DB_WRITER_URL is None:
        pytest.skip("DB_WRITER_URL not configured")
    if not USER or not PASSWORD:
        pytest.skip("UAT_TEST_USERNAME / UAT_TEST_PASSWORD not set in this shell")
    from app.core.database import dispose_engines
    from app.main import create_app

    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://uat-test"
    ) as client:
        yield client
    await dispose_engines()


async def _scalar(sql: str, **params):
    from app.core.database import get_db_session

    async with get_db_session(use_reader=True) as session:
        try:
            return (await session.execute(text(sql), params)).scalar()
        finally:
            await session.rollback()


async def _user_row() -> dict:
    from app.core.database import get_db_session

    async with get_db_session(use_reader=True) as session:
        try:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT TOP 1 Id, SecurityStamp, AccessFailedCount, PasswordHash "
                            "FROM dbo.ApplicationUsers WHERE UPPER(UserName) = UPPER(:u) ORDER BY Id"
                        ),
                        {"u": USER},
                    )
                )
                .mappings()
                .one()
            )
            return dict(row)
        finally:
            await session.rollback()


async def _fingerprints() -> dict[str, int | None]:
    result = {}
    for table in UNCHANGED_TABLES:
        result[table] = await _scalar(
            f"SELECT CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM dbo.[{table}]"  # noqa: S608 - fixed names
        )
    return result


async def _login(client: AsyncClient, password: str | None = None):
    return await client.post(
        "/auth/login", json={"userName": USER, "password": password or PASSWORD}
    )


async def test_pt2_login_with_the_cp_web_password_and_side_effects(uat):
    before = await _user_row()
    tables_before = await _fingerprints()
    logins_before = await _scalar(
        "SELECT COUNT(*) FROM dbo.LogUserLogins WHERE UserId = :id", id=before["Id"]
    )

    r = await _login(uat)
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["user"]["id"] == before["Id"]
    assert body["currentSiteId"] is not None

    after = await _user_row()
    stamp_renewed = after["SecurityStamp"] != before["SecurityStamp"]
    hash_unchanged = after["PasswordHash"] == before["PasswordHash"]
    assert stamp_renewed, "SecurityStamp was not renewed"
    assert hash_unchanged, "PasswordHash changed on login"
    assert (
        await _scalar("SELECT COUNT(*) FROM dbo.LogUserLogins WHERE UserId = :id", id=before["Id"])
        == logins_before + 1
    )
    assert await _fingerprints() == tables_before


async def test_wrong_password_changes_stamp_only(uat):
    before = await _user_row()
    logins_before = await _scalar(
        "SELECT COUNT(*) FROM dbo.LogUserLogins WHERE UserId = :id", id=before["Id"]
    )
    r = await _login(uat, password="Definitely-Wrong-1!")
    assert r.status_code == 401
    after = await _user_row()
    stamp_renewed = after["SecurityStamp"] != before["SecurityStamp"]
    assert stamp_renewed, "SecurityStamp was not renewed"
    assert after["AccessFailedCount"] == before["AccessFailedCount"]
    assert (
        await _scalar("SELECT COUNT(*) FROM dbo.LogUserLogins WHERE UserId = :id", id=before["Id"])
        == logins_before
    )


async def test_me_refresh_logout(uat):
    tokens = (await _login(uat)).json()
    h = {"Authorization": f"Bearer {tokens['accessToken']}"}
    assert (await uat.get("/auth/me", headers=h)).status_code == 200
    r = await uat.post("/auth/refresh-token", json={"refreshToken": tokens["refreshToken"]})
    assert r.status_code == 200
    assert (await uat.post("/auth/logout", headers=h)).status_code == 204
    assert (await uat.get("/auth/me", headers=h)).status_code == 401


async def test_forgot_password_queues_otp_without_exposing_it(uat):
    user = await _user_row()
    queued_before = await _scalar(
        "SELECT COUNT(*) FROM dbo.AlertQueues WHERE CreatedByUserId = :id", id=user["Id"]
    )
    r = await uat.post("/auth/forgot-password", json={"userName": USER})
    assert r.status_code == 200, r.json()
    assert set(r.json()) == {"challengeId"}
    queued_after = await _scalar(
        "SELECT COUNT(*) FROM dbo.AlertQueues WHERE CreatedByUserId = :id", id=user["Id"]
    )
    # +1 when the 'Forgot Password OTP' alert is enabled for the site, else 0 (legacy rules)
    assert queued_after - queued_before in (0, 1)


async def _latest_otp(user_id: int) -> str | None:
    message = await _scalar(
        "SELECT TOP 1 q.Message FROM dbo.AlertQueues q JOIN dbo.Alerts a ON a.Id = q.AlertId "
        "WHERE q.CreatedByUserId = :id AND a.Name = 'Forgot Password OTP' ORDER BY q.Id DESC",
        id=user_id,
    )
    found = re.findall(r"\b\d{6}\b", message or "")
    return found[-1] if found else None


async def test_pt2_reset_and_change_to_the_same_password(uat):
    if not ALLOW_WRITE:
        pytest.skip("set UAT_ALLOW_PASSWORD_WRITE=1 to run the password round trips")
    user = await _user_row()
    challenge = (await uat.post("/auth/forgot-password", json={"userName": USER})).json()
    otp = await _latest_otp(user["Id"])
    if otp is None:
        pytest.skip("'Forgot Password OTP' alert is disabled in UAT: no OTP row to read")
    v = await uat.post(
        "/auth/verify-otp",
        json={"userName": USER, "challengeId": challenge["challengeId"], "otp": otp},
    )
    assert v.status_code == 200
    ticket = v.json()["resetTicket"]
    body = {
        "userName": USER,
        "resetTicket": ticket,
        "password": PASSWORD,
        "confirmPassword": PASSWORD,
    }
    assert (await uat.post("/auth/reset-password", json=body)).status_code == 204
    after_reset = await _user_row()
    new_hash = after_reset["PasswordHash"] != user["PasswordHash"]  # new salt, same password
    assert new_hash, "PasswordHash not rewritten by reset"
    assert (await uat.post("/auth/reset-password", json=body)).status_code == 400  # reused

    tokens = (await _login(uat)).json()
    r = await uat.post(
        "/auth/change-password",
        json={"oldPassword": PASSWORD, "newPassword": PASSWORD, "confirmPassword": PASSWORD},
        headers={"Authorization": f"Bearer {tokens['accessToken']}"},
    )
    assert r.status_code == 204
    assert (await _login(uat)).status_code == 200
