"""
P1-M2 API tests (01d A1-A10) on a synthetic SQLite copy of the legacy tables.

Covers legacy order and messages, side effects (SecurityStamp, AccessFailedCount,
LogUserLogins, AlertQueues), refresh rotation/replay/logout, own-account rules,
forgot/OTP/reset with the F1 negatives, and that no secret reaches a response or a log.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import uuid

from httpx import ASGITransport, AsyncClient
import jwt
import pytest
from sqlalchemy import func, select
from structlog.testing import capture_logs

from app.core.database import get_reader_db, get_writer_db
from app.core.identity_password import verify_password
from app.core.security import get_auth_runtime
from app.models.legacy import AlertQueue, ApplicationUser, LogUserLogin
from tests.auth_support import (
    GOOD_PASSWORD,
    Seed,
    add_sub_division_user,
    make_engine,
    seed,
    session_dependency,
    set_site_alert,
)


NEW_PASSWORD = "Changed#987"


@dataclass
class Env:
    client: AsyncClient
    factory: object
    seed: Seed


@pytest.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ALERT_FROM_ADDRESS", "support@example.test")
    from app.main import create_app

    engine = await make_engine(tmp_path)
    dep, factory = session_dependency(engine)
    data = await seed(factory)
    app = create_app()
    app.dependency_overrides[get_writer_db] = dep
    app.dependency_overrides[get_reader_db] = dep
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("10.1.2.3", 5000)), base_url="http://test"
    ) as client:
        yield Env(client, factory, data)
    await engine.dispose()


async def _user(env: Env, user_id: int) -> ApplicationUser:
    async with env.factory() as s:
        return await s.get(ApplicationUser, user_id)


async def _count(env: Env, model) -> int:
    async with env.factory() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


async def _rows(env: Env, model):
    async with env.factory() as s:
        return list((await s.execute(select(model).order_by(model.id))).scalars())


async def _login(env: Env, user_name="synthetic.admin", password=GOOD_PASSWORD, **extra):
    body = {"userName": user_name, "password": password, **extra}
    return await env.client.post(
        "/auth/login", json=body, headers={"User-Agent": "Mozilla/5.0 Chrome/118.0.1 Safari/537.36"}
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── A1 login ────────────────────────────────────────────────────────────────


async def test_login_success_returns_tokens_context_and_logs_the_login(env):
    before = await _user(env, env.seed.admin_id)
    r = await _login(env)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tokenType"] == "Bearer"
    assert body["rememberMe"] is False
    assert body["user"]["userName"] == "synthetic.admin"
    assert body["permissions"] == ["View User", "Save User"]
    assert body["flags"] == {
        "isSuperAdmin": False,
        "isSystemAdmin": False,
        "isSiteAdmin": False,
        "isEndUser": False,
        "isSubDivision": False,
    }
    assert [s["id"] for s in body["sites"]] == [env.seed.site_b, env.seed.site_a]
    assert body["currentSiteId"] == env.seed.site_b  # first UserSites row
    assert "passwordHash" not in r.text and "securityStamp" not in r.text

    after = await _user(env, env.seed.admin_id)
    assert after.security_stamp != before.security_stamp
    logs = await _rows(env, LogUserLogin)
    assert len(logs) == 1
    log_row = logs[0]
    assert (log_row.user_id, log_row.site_id, log_row.ip) == (
        env.seed.admin_id,
        env.seed.site_b,
        "10.1.2.3",
    )
    assert log_row.user_name == "synthetic.admin"
    assert log_row.web_request_identification.startswith("Machine Name=")
    assert (
        "IP Address=10.1.2.3;Logon User=;Browser Name=Chrome;Browser Version=118.0"
        in log_row.web_request_identification
    )
    assert await _count(env, AlertQueue) == 0  # no meterNo → no login alert


async def test_login_by_email_and_case_insensitive_user_name(env):
    assert (await _login(env, user_name="SYNTHETIC.ADMIN")).status_code == 200
    r = await _login(env, user_name="enduser@example.test")
    assert r.status_code == 200
    assert r.json()["user"]["userName"] == "synthetic.enduser"


async def test_x_forwarded_for_first_entry_is_logged(env):
    r = await env.client.post(
        "/auth/login",
        json={"userName": "synthetic.admin", "password": GOOD_PASSWORD},
        headers={"X-Forwarded-For": "203.0.113.9, 10.0.0.1"},
    )
    assert r.status_code == 200
    assert (await _rows(env, LogUserLogin))[0].ip == "203.0.113.9"


async def test_login_validation_messages_are_legacy(env):
    r = await env.client.post("/auth/login", json={})
    assert r.status_code == 422
    assert [e["message"] for e in r.json()["errors"]] == [
        "The Email field is required.",
        "The Password field is required.",
    ]


async def test_unknown_user_is_an_invalid_login_and_writes_nothing(env):
    r = await _login(env, user_name="nobody")
    assert r.status_code == 401
    assert r.json() == {"errorCode": "INVALID_LOGIN", "message": "Invalid login attempt."}
    assert await _count(env, LogUserLogin) == 0


async def test_wrong_password_updates_stamp_but_not_failed_count(env):
    before = await _user(env, env.seed.admin_id)
    r = await _login(env, password="Wrong@123")
    assert r.status_code == 401
    assert r.json()["message"] == "Invalid login attempt."
    after = await _user(env, env.seed.admin_id)
    assert after.security_stamp != before.security_stamp  # legacy: stamp first
    assert after.access_failed_count == 0  # shouldLockout: false (F5 kept)
    assert await _count(env, LogUserLogin) == 0


async def test_disabled_user_is_rejected_after_the_stamp_update(env):
    async with env.factory() as s:
        u = await s.get(ApplicationUser, env.seed.admin_id)
        u.status_id = 0
        old_stamp = u.security_stamp
        await s.commit()
    r = await _login(env)
    assert r.status_code == 403
    assert r.json() == {
        "errorCode": "ACCOUNT_DISABLED",
        "message": "Your account is not enabled. Please contact administrator.",
    }
    assert (await _user(env, env.seed.admin_id)).security_stamp != old_stamp


async def test_locked_out_user_is_rejected(env):
    async with env.factory() as s:
        u = await s.get(ApplicationUser, env.seed.admin_id)
        u.lockout_end_date_utc = (datetime.now(UTC) + timedelta(minutes=5)).replace(tzinfo=None)
        await s.commit()
    r = await _login(env)
    assert r.status_code == 403
    assert r.json()["errorCode"] == "ACCOUNT_LOCKED"


async def test_expired_lockout_or_lockout_disabled_allows_login(env):
    async with env.factory() as s:
        u = await s.get(ApplicationUser, env.seed.admin_id)
        u.lockout_end_date_utc = (datetime.now(UTC) + timedelta(minutes=5)).replace(tzinfo=None)
        u.lockout_enabled = False
        await s.commit()
    assert (await _login(env)).status_code == 200


async def test_successful_login_resets_access_failed_count(env):
    async with env.factory() as s:
        u = await s.get(ApplicationUser, env.seed.admin_id)
        u.access_failed_count = 3
        await s.commit()
    assert (await _login(env)).status_code == 200
    assert (await _user(env, env.seed.admin_id)).access_failed_count == 0


async def test_two_factor_users_are_refused(env):
    async with env.factory() as s:
        u = await s.get(ApplicationUser, env.seed.admin_id)
        u.two_factor_enabled = True
        await s.commit()
    r = await _login(env)
    assert r.status_code == 403
    assert r.json()["errorCode"] == "TWO_FACTOR_NOT_SUPPORTED"
    assert await _count(env, LogUserLogin) == 0


async def test_user_without_site_cannot_log_in(env):
    r = await _login(env, user_name="synthetic.nosite")
    assert r.status_code == 403
    assert r.json()["errorCode"] == "NO_SITE_ASSIGNED"
    assert await _count(env, LogUserLogin) == 0


async def test_super_admin_sees_all_sites_and_defaults_to_first_by_name(env):
    r = await _login(env, user_name="synthetic.super")
    body = r.json()
    assert body["flags"]["isSuperAdmin"] is True
    assert [s["name"] for s in body["sites"]] == ["Alpha Heights", "Zeta Towers"]
    assert body["currentSiteId"] == env.seed.site_a
    assert (await _rows(env, LogUserLogin))[0].site_id == env.seed.site_a


async def test_sub_division_user_gets_tower_ids(env):
    await add_sub_division_user(env.factory, env.seed.site_a)
    r = await _login(env, user_name="synthetic.subdiv")
    assert r.json()["flags"]["isSubDivision"] is True
    assert len(r.json()["towerIds"]) == 1


# ── A1 meterNo / login alert (D5) ───────────────────────────────────────────


async def test_valid_meter_no_queues_the_login_alert(env):
    r = await _login(env, meterNo="MTR000001")
    assert r.status_code == 200
    rows = await _rows(env, AlertQueue)
    assert len(rows) == 1
    q = rows[0]
    assert q.message == "Crystal Power: synthetic.admin logged in"
    assert q.to_address == "9000000001"  # SMS → phone
    assert q.from_address == "support@example.test"
    assert (q.site_id, q.meter_no, q.meter_status_id) == (env.seed.site_b, "MTR000001", 1)
    assert (q.alert_id, q.delivery_status_id, q.is_sent) == (env.seed.login_alert_id, 101, False)
    assert q.created_by_user_id == env.seed.admin_id
    assert isinstance(q.guid, uuid.UUID)
    assert await _count(env, LogUserLogin) == 1


async def test_meter_on_another_site_or_unknown_queues_nothing(env):
    assert (await _login(env, meterNo="MTR000002")).status_code == 200  # site A, current = B
    assert (await _login(env, meterNo="NOPE")).status_code == 200
    assert await _count(env, AlertQueue) == 0
    assert await _count(env, LogUserLogin) == 2


async def test_login_alert_skipped_for_end_users_and_site_admins(env):
    for name in ("synthetic.enduser", "synthetic.siteadmin"):
        assert (await _login(env, user_name=name, meterNo="MTR000002")).status_code == 200
    assert await _count(env, AlertQueue) == 0


async def test_login_alert_respects_disabled_site_alert(env):
    await set_site_alert(env.factory, env.seed.login_alert_id, env.seed.site_b, status=0)
    assert (await _login(env, meterNo="MTR000001")).status_code == 200
    assert await _count(env, AlertQueue) == 0


async def test_site_alert_ignored_when_alert_not_editable_at_site_level(env):
    await set_site_alert(
        env.factory, env.seed.login_alert_id, env.seed.site_b, status=0, editable=False
    )
    assert (await _login(env, meterNo="MTR000001")).status_code == 200
    assert await _count(env, AlertQueue) == 1


# ── A2 refresh / A3 logout / A4 me ──────────────────────────────────────────


async def test_refresh_rotates_and_replay_revokes_the_session(env):
    tokens = (await _login(env, rememberMe=True)).json()
    assert tokens["rememberMe"] is True
    r1 = await env.client.post("/auth/refresh-token", json={"refreshToken": tokens["refreshToken"]})
    assert r1.status_code == 200
    new = r1.json()
    assert new["refreshToken"] != tokens["refreshToken"]
    assert new["rememberMe"] is True

    replay = await env.client.post(
        "/auth/refresh-token", json={"refreshToken": tokens["refreshToken"]}
    )
    assert replay.status_code == 401
    assert replay.json()["errorCode"] == "REFRESH_TOKEN_REUSED"
    # the whole session is gone, including the newest tokens
    again = await env.client.post("/auth/refresh-token", json={"refreshToken": new["refreshToken"]})
    assert again.status_code == 401
    me = await env.client.get("/auth/me", headers=_bearer(new["accessToken"]))
    assert me.status_code == 401
    assert me.headers["X-Session-Expired"] == "true"


async def test_refresh_rejects_garbage_and_unknown_sessions(env):
    for token in (None, "", "abc", "nosuch.session"):
        r = await env.client.post("/auth/refresh-token", json={"refreshToken": token})
        assert r.status_code == 401
        assert r.json()["errorCode"] == "REFRESH_TOKEN_INVALID"


async def test_refresh_fails_after_the_security_stamp_changes(env):
    tokens = (await _login(env)).json()
    await _login(env, password="Wrong@123")  # any login attempt renews the stamp (legacy)
    r = await env.client.post("/auth/refresh-token", json={"refreshToken": tokens["refreshToken"]})
    assert r.status_code == 401
    assert r.json()["errorCode"] == "SESSION_ENDED"


async def test_expired_refresh_token_is_rejected(env):
    tokens = (await _login(env)).json()
    runtime = get_auth_runtime()
    sid = tokens["refreshToken"].split(".")[0]
    runtime.sessions._sessions[sid].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    r = await env.client.post("/auth/refresh-token", json={"refreshToken": tokens["refreshToken"]})
    assert r.json()["errorCode"] == "REFRESH_TOKEN_EXPIRED"


async def test_logout_ends_access_and_refresh(env):
    tokens = (await _login(env)).json()
    h = _bearer(tokens["accessToken"])
    assert (await env.client.get("/auth/me", headers=h)).status_code == 200
    assert (await env.client.post("/auth/logout", headers=h)).status_code == 204
    assert (await env.client.get("/auth/me", headers=h)).status_code == 401
    r = await env.client.post("/auth/refresh-token", json={"refreshToken": tokens["refreshToken"]})
    assert r.json()["errorCode"] == "SESSION_ENDED"


async def test_protected_endpoints_need_a_valid_bearer(env):
    assert (await env.client.get("/auth/me")).status_code == 401
    assert (await env.client.get("/auth/me", headers=_bearer("x.y.z"))).status_code == 401
    assert (await env.client.post("/auth/logout")).status_code == 401
    assert (await env.client.put("/auth/me", json={})).status_code == 401
    assert (await env.client.post("/auth/change-password", json={})).status_code == 401


async def test_expired_access_token_says_so(env):
    tokens = (await _login(env)).json()
    payload = jwt.decode(tokens["accessToken"], options={"verify_signature": False})
    payload["exp"] = int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())
    expired = jwt.encode(payload, get_auth_runtime().tokens._private_key, algorithm="RS256")
    r = await env.client.get("/auth/me", headers=_bearer(expired))
    assert r.status_code == 401
    assert r.json()["errorCode"] == "TOKEN_EXPIRED"
    assert r.headers["X-Token-Expired"] == "true"


async def test_me_returns_profile_and_context(env):
    tokens = (await _login(env)).json()
    r = await env.client.get("/auth/me", headers=_bearer(tokens["accessToken"]))
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["id"] == env.seed.admin_id
    assert body["currentSiteId"] == env.seed.site_b
    assert set(body) == {"user", "permissions", "flags", "sites", "towerIds", "currentSiteId"}


# ── A5 update own profile ───────────────────────────────────────────────────


async def test_update_me_changes_only_email_and_phone(env):
    tokens = (await _login(env)).json()
    before = await _user(env, env.seed.admin_id)
    r = await env.client.put(
        "/auth/me",
        json={"email": "new@example.test", "phoneNumber": "8123456789", "fullName": "Ignored"},
        headers=_bearer(tokens["accessToken"]),
    )
    assert r.status_code == 200, r.text
    after = await _user(env, env.seed.admin_id)
    assert (after.email, after.phone_number) == ("new@example.test", "8123456789")
    assert after.full_name == before.full_name
    assert after.updated_date == before.updated_date
    assert after.security_stamp == before.security_stamp


@pytest.mark.parametrize(
    ("body", "messages"),
    [
        ({}, ["The Email field is required.", "The Phone No. field is required."]),
        ({"email": "a@b.c", "phoneNumber": "6123456789"}, ["Not a valid Phone number"]),
        (
            {"email": "a@b.c", "phoneNumber": "91234567890"},
            [
                "The field Phone No. must be a string with a maximum length of 10.",
                "Not a valid Phone number",
            ],
        ),
        (
            {"email": "a@b.c", "phoneNumber": "abc"},
            ["The Phone No. field is not a valid phone number.", "Not a valid Phone number"],
        ),
    ],
)
async def test_update_me_validation_is_legacy(env, body, messages):
    tokens = (await _login(env)).json()
    r = await env.client.put("/auth/me", json=body, headers=_bearer(tokens["accessToken"]))
    assert r.status_code == 422
    assert [e["message"] for e in r.json()["errors"]] == messages


async def test_site_admin_cannot_edit_profile(env):
    tokens = (await _login(env, user_name="synthetic.siteadmin")).json()
    r = await env.client.put(
        "/auth/me",
        json={"email": "x@example.test", "phoneNumber": "9123456789"},
        headers=_bearer(tokens["accessToken"]),
    )
    assert r.status_code == 403


# ── A6 change own password ──────────────────────────────────────────────────


async def test_change_password_writes_v2_hash_and_new_stamp_and_keeps_own_session(env):
    other = (await _login(env)).json()
    # every login renews the stamp (legacy), so only the latest session stays valid
    tokens = (await _login(env)).json()
    h = _bearer(tokens["accessToken"])
    before = await _user(env, env.seed.admin_id)
    r = await env.client.post(
        "/auth/change-password",
        json={
            "oldPassword": GOOD_PASSWORD,
            "newPassword": NEW_PASSWORD,
            "confirmPassword": NEW_PASSWORD,
        },
        headers=h,
    )
    assert r.status_code == 204, r.text
    after = await _user(env, env.seed.admin_id)
    assert verify_password(after.password_hash, NEW_PASSWORD)
    assert after.security_stamp != before.security_stamp
    # own session survives a refresh; the old one does not
    ok = await env.client.post("/auth/refresh-token", json={"refreshToken": tokens["refreshToken"]})
    assert ok.status_code == 200
    gone = await env.client.post(
        "/auth/refresh-token", json={"refreshToken": other["refreshToken"]}
    )
    assert gone.status_code == 401
    assert (await _login(env, password=NEW_PASSWORD)).status_code == 200


async def test_change_password_errors(env):
    h = _bearer((await _login(env)).json()["accessToken"])
    r = await env.client.post("/auth/change-password", json={}, headers=h)
    assert [e["message"] for e in r.json()["errors"]] == [
        "The Current password field is required.",
        "The New password field is required.",
    ]
    r = await env.client.post(
        "/auth/change-password",
        json={"oldPassword": "x", "newPassword": "abcdef", "confirmPassword": "abcdeg"},
        headers=h,
    )
    assert (
        r.json()["errors"][0]["message"]
        == "The new password and confirmation password do not match."
    )
    r = await env.client.post(
        "/auth/change-password",
        json={"oldPassword": "x", "newPassword": "abc", "confirmPassword": "abc"},
        headers=h,
    )
    assert (
        r.json()["errors"][0]["message"] == "The New password must be at least 6 characters long."
    )
    r = await env.client.post(
        "/auth/change-password",
        json={
            "oldPassword": "Wrong@123",
            "newPassword": NEW_PASSWORD,
            "confirmPassword": NEW_PASSWORD,
        },
        headers=h,
    )
    assert (r.status_code, r.json()["message"]) == (400, "Incorrect password.")
    r = await env.client.post(
        "/auth/change-password",
        json={"oldPassword": GOOD_PASSWORD, "newPassword": "abcdefg", "confirmPassword": "abcdefg"},
        headers=h,
    )
    assert r.json()["errorCode"] == "PASSWORD_POLICY"
    assert r.json()["message"] == (
        "Passwords must have at least one non letter or digit character. "
        "Passwords must have at least one digit ('0'-'9'). "
        "Passwords must have at least one uppercase ('A'-'Z')."
    )


# ── A7-A9 forgot password / OTP / reset (F1) ────────────────────────────────


async def _otp_from_queue(env: Env) -> str:
    """Test-only retrieval from AlertQueues (D4) — the API never returns it."""
    rows = await _rows(env, AlertQueue)
    return rows[-1].message.rsplit(" ", 1)[-1]


async def _forgot(env: Env, user_name="synthetic.admin"):
    return await env.client.post("/auth/forgot-password", json={"userName": user_name})


async def test_forgot_password_queues_otp_and_returns_only_a_challenge(env):
    with capture_logs() as logs:
        r = await _forgot(env)
    assert r.status_code == 200
    assert set(r.json()) == {"challengeId"}
    rows = await _rows(env, AlertQueue)
    assert len(rows) == 1
    q = rows[0]
    otp = q.message.rsplit(" ", 1)[-1]
    assert q.message == f"Your OTP is {otp}" and len(otp) == 6 and otp.isdigit()
    assert otp not in r.text
    assert (q.site_id, q.alert_id, q.to_address) == (
        env.seed.site_b,
        env.seed.otp_alert_id,
        "9000000001",
    )
    assert q.meter_no is None
    assert otp not in repr(logs)


async def test_forgot_password_for_user_without_site_has_null_site(env):
    assert (await _forgot(env, "synthetic.nosite")).status_code == 200
    assert (await _rows(env, AlertQueue))[0].site_id is None


async def test_forgot_password_site_alert_disabled_queues_nothing_but_answers(env):
    await set_site_alert(env.factory, env.seed.otp_alert_id, env.seed.site_b, status=0)
    r = await _forgot(env)
    assert r.status_code == 200
    assert await _count(env, AlertQueue) == 0


@pytest.mark.parametrize(
    ("change", "status", "code", "message"),
    [
        (None, 404, "ACCOUNT_NOT_FOUND", "No Account was found by this username."),
        (
            {"status_id": 0},
            403,
            "ACCOUNT_DISABLED",
            "Your account is not enabled. Please contact administrator.",
        ),
        ({"email_confirmed": False}, 400, "EMAIL_NOT_VERIFIED", "Account Email is not verified."),
        (
            {"phone_number": ""},
            400,
            "NO_MOBILE_NUMBER",
            " No Mobile Number registerd for the User.",
        ),
    ],
)
async def test_forgot_password_legacy_checks(env, change, status, code, message):
    name = "nobody"
    if change:
        name = "synthetic.admin"
        async with env.factory() as s:
            u = await s.get(ApplicationUser, env.seed.admin_id)
            for k, v in change.items():
                setattr(u, k, v)
            await s.commit()
    r = await _forgot(env, name)
    assert (r.status_code, r.json()["errorCode"], r.json()["message"]) == (status, code, message)
    assert await _count(env, AlertQueue) == 0


async def test_full_reset_flow_and_ticket_cannot_be_reused(env):
    challenge = (await _forgot(env)).json()["challengeId"]
    otp = await _otp_from_queue(env)
    v = await env.client.post(
        "/auth/verify-otp",
        json={"userName": "synthetic.admin", "challengeId": challenge, "otp": otp},
    )
    assert v.status_code == 200
    ticket = v.json()["resetTicket"]
    body = {
        "userName": "synthetic.admin",
        "resetTicket": ticket,
        "password": NEW_PASSWORD,
        "confirmPassword": NEW_PASSWORD,
    }
    before = await _user(env, env.seed.admin_id)
    assert (await env.client.post("/auth/reset-password", json=body)).status_code == 204
    after = await _user(env, env.seed.admin_id)
    assert verify_password(after.password_hash, NEW_PASSWORD)
    assert after.security_stamp != before.security_stamp
    # reused ticket (stamp changed)
    again = await env.client.post(
        "/auth/reset-password",
        json={**body, "password": "Other@111", "confirmPassword": "Other@111"},
    )
    assert (again.status_code, again.json()["message"]) == (400, "Invalid token.")
    # reused OTP / challenge
    v2 = await env.client.post(
        "/auth/verify-otp",
        json={"userName": "synthetic.admin", "challengeId": challenge, "otp": otp},
    )
    assert v2.status_code == 400
    assert (await _login(env, password=NEW_PASSWORD)).status_code == 200


async def test_reset_requires_a_valid_ticket(env):
    challenge = (await _forgot(env)).json()["challengeId"]
    otp = await _otp_from_queue(env)
    base = {
        "userName": "synthetic.admin",
        "password": NEW_PASSWORD,
        "confirmPassword": NEW_PASSWORD,
    }
    runtime = get_auth_runtime()
    admin = await _user(env, env.seed.admin_id)
    other = await _user(env, env.seed.end_user_id)
    expired_settings_ticket = jwt.encode(
        {
            "iss": "prime-mdm-backend",
            "aud": "prime-mdm-password-reset",
            "sub": str(admin.id),
            "sst": runtime.tokens.stamp_fingerprint(admin.security_stamp),
            "iat": 0,
            "exp": int((datetime.now(UTC) - timedelta(minutes=1)).timestamp()),
            "jti": "x",
            "typ": "reset_ticket",
        },
        runtime.tokens._otp_key,
        algorithm="HS256",
    )
    bad_tickets = {
        "missing": None,
        "incorrect": "not-a-ticket",
        "challenge_instead_of_ticket": challenge,
        "expired": expired_settings_ticket,
        "other_user": runtime.tokens.create_reset_ticket(other.id, other.security_stamp),
        "forged": jwt.encode({"sub": str(admin.id)}, "g" * 32, algorithm="HS256"),
    }
    for label, ticket in bad_tickets.items():
        r = await env.client.post("/auth/reset-password", json={**base, "resetTicket": ticket})
        assert (r.status_code, r.json()["message"]) == (400, "Invalid token."), label
    assert verify_password((await _user(env, env.seed.admin_id)).password_hash, GOOD_PASSWORD)
    assert otp  # the OTP alone is never enough


async def test_verify_otp_rejections(env):
    challenge = (await _forgot(env)).json()["challengeId"]
    otp = await _otp_from_queue(env)
    wrong = "000000" if otp != "000000" else "111111"
    cases = [
        {"userName": "synthetic.admin", "challengeId": challenge, "otp": wrong},
        {"userName": "synthetic.admin", "challengeId": challenge, "otp": otp + "1"},
        {"userName": "synthetic.admin", "challengeId": challenge},
        {"userName": "synthetic.admin", "otp": otp},
        {"userName": "synthetic.enduser", "challengeId": challenge, "otp": otp},
        {"userName": "nobody", "challengeId": challenge, "otp": otp},
    ]
    for body in cases:
        r = await env.client.post("/auth/verify-otp", json=body)
        assert (r.status_code, r.json()["message"]) == (
            400,
            "Invalid/Expired OTP. Please try again.",
        )


async def test_login_between_forgot_and_verify_invalidates_the_otp(env):
    challenge = (await _forgot(env)).json()["challengeId"]
    otp = await _otp_from_queue(env)
    await _login(env)  # renews the stamp, as legacy (reset token is stamp-bound)
    r = await env.client.post(
        "/auth/verify-otp",
        json={"userName": "synthetic.admin", "challengeId": challenge, "otp": otp},
    )
    assert r.status_code == 400


async def test_reset_unknown_user_answers_like_success(env):
    r = await env.client.post(
        "/auth/reset-password",
        json={
            "userName": "nobody",
            "resetTicket": "x",
            "password": NEW_PASSWORD,
            "confirmPassword": NEW_PASSWORD,
        },
    )
    assert r.status_code == 204


async def test_reset_validation_and_policy(env):
    r = await env.client.post("/auth/reset-password", json={})
    assert [e["message"] for e in r.json()["errors"]] == [
        "The User Name field is required.",
        "The Password field is required.",
    ]
    r = await env.client.post(
        "/auth/reset-password",
        json={"userName": "synthetic.admin", "password": "abcdef", "confirmPassword": "x"},
    )
    assert (
        r.json()["errors"][0]["message"] == "The password and confirmation password do not match."
    )
    await _forgot(env)
    challenge = (await _forgot(env)).json()["challengeId"]
    otp = await _otp_from_queue(env)
    ticket = (
        await env.client.post(
            "/auth/verify-otp",
            json={"userName": "synthetic.admin", "challengeId": challenge, "otp": otp},
        )
    ).json()["resetTicket"]
    r = await env.client.post(
        "/auth/reset-password",
        json={
            "userName": "synthetic.admin",
            "resetTicket": ticket,
            "password": "abcdefg",
            "confirmPassword": "abcdefg",
        },
    )
    assert r.json()["errorCode"] == "PASSWORD_POLICY"


async def test_forgot_password_validation(env):
    r = await env.client.post("/auth/forgot-password", json={"userName": " "})
    assert r.json()["errors"][0]["message"] == "The User Name field is required."


# ── A10 policy, Swagger, secrets in logs ────────────────────────────────────


async def test_password_policy(env):
    r = await env.client.get("/auth/password-policy")
    assert r.json() == {
        "requiredLength": 6,
        "requireNonLetterOrDigit": True,
        "requireDigit": True,
        "requireLowercase": True,
        "requireUppercase": True,
    }


async def test_openapi_documents_bearer_auth(env):
    spec = (await env.client.get("/openapi.json")).json()
    assert spec["components"]["securitySchemes"]["bearer"]["scheme"] == "bearer"
    assert {"/auth/login", "/auth/me", "/auth/reset-password"} <= set(spec["paths"])
    assert spec["paths"]["/auth/me"]["get"]["security"] == [{"bearer": []}]


async def test_no_secret_is_logged(env):
    with capture_logs() as logs:
        tokens = (await _login(env, meterNo="MTR000001")).json()
        await _login(env, password="Wrong@123")
        await env.client.post("/auth/refresh-token", json={"refreshToken": tokens["refreshToken"]})
        await env.client.post("/auth/refresh-token", json={"refreshToken": tokens["refreshToken"]})
        await _forgot(env)
    text = repr(logs)
    otp = await _otp_from_queue(env)
    for secret in (GOOD_PASSWORD, "Wrong@123", tokens["refreshToken"], tokens["accessToken"], otp):
        assert secret not in text
    assert "9000000001" not in text and "synthetic.admin" not in text


# ── AddAlertQueue edge cases (legacy would throw; here nothing is queued) ───


async def _alert_outcome(
    env: Env, change: dict, *, from_address="support@example.test", user_change=None
):
    from app.core.config import Settings
    from app.models.legacy import Alert
    from app.schemas.auth import Flags
    from app.services.alert_queue_service import MeterRef, queue_login_alert

    async with env.factory() as s:
        alert = await s.get(Alert, env.seed.login_alert_id)
        for k, v in change.items():
            setattr(alert, k, v)
        u = await s.get(ApplicationUser, env.seed.admin_id)
        for k, v in (user_change or {}).items():
            setattr(u, k, v)
        await s.commit()
        settings = Settings(ENVIRONMENT="test", ALERT_FROM_ADDRESS=from_address)
        meter = MeterRef("MTR000001", 0, 1)  # SiteId <= 0 → current site
        outcome = await queue_login_alert(s, settings, u, Flags(), meter, env.seed.site_a)
        await s.commit()
        return outcome


@pytest.mark.parametrize(
    ("change", "kwargs", "expected"),
    [
        ({"status_id": 0}, {}, "alert_disabled"),
        ({"name": "Renamed"}, {}, "alert_missing"),
        ({"message": None}, {}, "no_message"),
        ({}, {"from_address": None}, "no_from_address"),
        ({}, {"user_change": {"phone_number": None}}, "no_to_address"),
    ],
)
async def test_alert_queue_edge_cases(env, change, kwargs, expected):
    assert (await _alert_outcome(env, change, **kwargs)).value == expected
    assert await _count(env, AlertQueue) == 0


async def test_email_alert_goes_to_the_email_and_current_site(env):
    assert (await _alert_outcome(env, {"delivery_method_id": 1})).value == "queued"
    q = (await _rows(env, AlertQueue))[0]
    assert (q.to_address, q.delivery_method_id, q.site_id) == (
        "synthetic@example.test",
        1,
        env.seed.site_a,
    )
