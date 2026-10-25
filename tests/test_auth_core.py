"""Unit tests for the P1-M2 building blocks (no database)."""

import base64
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import pytest
from starlette.requests import Request

from app.core.config import Settings, validate_auth_config
from app.core.exceptions import CredentialsError, TokenExpiredError
from app.core.identity_password import (
    hash_password,
    new_security_stamp,
    password_policy_errors,
    verify_password,
)
from app.core.request_info import browser, client_ip, web_request_identification
from app.core.session_registry import RefreshOutcome, SessionRegistry
from app.core.tokens import TokenService
from app.services.auth_service import is_locked_out, requires_two_factor
from tests.auth_support import user


# ── Identity v2 hash ────────────────────────────────────────────────────────


def test_hash_has_identity_v2_layout_and_random_salt():
    h1, h2 = hash_password("Test@1234"), hash_password("Test@1234")
    raw = base64.b64decode(h1)
    assert len(raw) == 49 and raw[0] == 0x00
    assert h1 != h2
    assert verify_password(h1, "Test@1234") and verify_password(h2, "Test@1234")


def test_hash_matches_an_independent_pbkdf2_implementation():
    raw = base64.b64decode(hash_password("Ünïcode#1"))
    kdf = PBKDF2HMAC(algorithm=hashes.SHA1(), length=32, salt=raw[1:17], iterations=1000)  # noqa: S303
    assert kdf.derive("Ünïcode#1".encode()) == raw[17:]


@pytest.mark.parametrize(
    "stored",
    [
        None,
        "",
        "not base64!",
        base64.b64encode(b"\x01" + b"0" * 48).decode(),
        base64.b64encode(b"\x00" * 10).decode(),
    ],
)
def test_verify_rejects_missing_or_malformed_hashes(stored):
    assert verify_password(stored, "Test@1234") is False


def test_verify_rejects_wrong_or_missing_password():
    h = hash_password("Test@1234")
    assert verify_password(h, "test@1234") is False
    assert verify_password(h, None) is False


def test_security_stamp_is_a_lower_case_guid():
    stamp = new_security_stamp()
    assert len(stamp) == 36 and stamp == stamp.lower() and stamp.count("-") == 4


@pytest.mark.parametrize(
    ("password", "expected"),
    [
        ("Test@1234", None),
        ("Ab1!xy", None),
        (
            "",
            "Passwords must be at least 6 characters. Passwords must have at least one non letter or digit character. Passwords must have at least one digit ('0'-'9'). Passwords must have at least one lowercase ('a'-'z'). Passwords must have at least one uppercase ('A'-'Z').",
        ),
        ("Ab1xyz", "Passwords must have at least one non letter or digit character."),
        ("AB1!XY", "Passwords must have at least one lowercase ('a'-'z')."),
        ("ab1!xy", "Passwords must have at least one uppercase ('A'-'Z')."),
        ("Abc!xy", "Passwords must have at least one digit ('0'-'9')."),
        ("Ab1éxy", "Passwords must have at least one non letter or digit character."),
    ],
)
def test_password_policy_messages(password, expected):
    assert password_policy_errors(password) == expected


# ── tokens ──────────────────────────────────────────────────────────────────


@pytest.fixture
def tokens():
    return TokenService(Settings(ENVIRONMENT="test"))


def test_access_token_round_trip(tokens):
    token, exp = tokens.create_access_token(42, "sid-1")
    claims = tokens.decode_access_token(token)
    assert (claims.user_id, claims.session_id) == (42, "sid-1")
    assert timedelta(minutes=29) < exp - datetime.now(UTC) <= timedelta(minutes=30)


def test_access_token_from_another_key_or_purpose_is_rejected(tokens):
    other = TokenService(Settings(ENVIRONMENT="test"))
    token, _ = other.create_access_token(1, "s")
    with pytest.raises(CredentialsError):
        tokens.decode_access_token(token)
    challenge, _ = tokens.create_otp_challenge(1, "stamp")
    with pytest.raises(CredentialsError):
        tokens.decode_access_token(challenge)


def test_expired_access_token(tokens):
    settings = Settings(ENVIRONMENT="test", ACCESS_TOKEN_MINUTES=1)
    service = TokenService(settings)
    import jwt

    token, _ = service.create_access_token(1, "s")
    payload = jwt.decode(token, options={"verify_signature": False})
    payload["exp"] = payload["iat"] - 10
    expired = jwt.encode(payload, service._private_key, algorithm="RS256")
    with pytest.raises(TokenExpiredError):
        service.decode_access_token(expired)


def test_otp_is_six_digits_bound_to_user_and_stamp(tokens):
    challenge, otp = tokens.create_otp_challenge(7, "stamp-a")
    assert len(otp) == 6 and otp.isdigit()
    assert tokens.verify_otp(challenge, otp, 7, "stamp-a")
    assert not tokens.verify_otp(challenge, otp, 8, "stamp-a")
    assert not tokens.verify_otp(challenge, otp, 7, "stamp-b")
    assert not tokens.verify_otp(challenge, None, 7, "stamp-a")
    assert not tokens.verify_otp(None, otp, 7, "stamp-a")
    assert otp not in challenge


def test_reset_ticket_is_bound_and_expires():
    service = TokenService(Settings(ENVIRONMENT="test", RESET_TICKET_TTL_MINUTES=1))
    ticket = service.create_reset_ticket(3, "s1")
    assert service.verify_reset_ticket(ticket, 3, "s1")
    assert not service.verify_reset_ticket(ticket, 4, "s1")
    assert not service.verify_reset_ticket(ticket, 3, "s2")
    challenge, _ = service.create_otp_challenge(3, "s1")
    assert not service.verify_reset_ticket(challenge, 3, "s1")


def test_configured_keys_are_used():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    settings = Settings(ENVIRONMENT="uat", JWT_PRIVATE_KEY_PEM=pem, OTP_SIGNING_KEY="k" * 32)
    a, b = TokenService(settings), TokenService(settings)
    token, _ = a.create_access_token(1, "s")
    assert b.decode_access_token(token).user_id == 1  # same key → survives a new instance
    challenge, otp = a.create_otp_challenge(1, "st")
    assert b.verify_otp(challenge, otp, 1, "st")


def test_auth_config_requires_keys_outside_local_and_test():
    validate_auth_config(Settings(ENVIRONMENT="local"))
    with pytest.raises(RuntimeError, match="JWT_PRIVATE_KEY_PEM, OTP_SIGNING_KEY"):
        validate_auth_config(Settings(ENVIRONMENT="uat"))
    with pytest.raises(RuntimeError, match="32 bytes"):
        validate_auth_config(Settings(ENVIRONMENT="local", OTP_SIGNING_KEY="short"))


# ── session registry ────────────────────────────────────────────────────────


def test_registry_rotation_replay_and_revocation():
    reg = SessionRegistry(refresh_days=14)
    issued = reg.create(1, remember_me=False, stamp_fingerprint="fp")
    assert reg.is_active(issued.session_id, 1)
    assert not reg.is_active(issued.session_id, 2)
    outcome, session, new = reg.rotate(issued.refresh_token)
    assert outcome is RefreshOutcome.OK and session.remember_me is False
    assert new.refresh_token != issued.refresh_token
    assert reg.rotate(issued.refresh_token)[0] is RefreshOutcome.REPLAYED
    assert reg.rotate(new.refresh_token)[0] is RefreshOutcome.REVOKED
    assert not reg.is_active(issued.session_id, 1)


def test_registry_rejects_unknown_wrong_and_expired():
    reg = SessionRegistry(refresh_days=14)
    issued = reg.create(1, remember_me=True, stamp_fingerprint="fp")
    assert reg.rotate(None)[0] is RefreshOutcome.INVALID
    assert reg.rotate("x")[0] is RefreshOutcome.INVALID
    assert reg.rotate(f"{issued.session_id}.wrong")[0] is RefreshOutcome.INVALID
    assert reg.rotate(f"{issued.session_id}.ü")[0] is RefreshOutcome.INVALID
    reg._sessions[issued.session_id].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert reg.rotate(issued.refresh_token)[0] is RefreshOutcome.EXPIRED


def test_registry_sliding_expiry_and_purge():
    reg = SessionRegistry(refresh_days=14)
    old = reg.create(1, remember_me=True, stamp_fingerprint="fp")
    reg._sessions[old.session_id].expires_at = datetime.now(UTC) - timedelta(days=1)
    fresh = reg.create(2, remember_me=True, stamp_fingerprint="fp")
    assert old.session_id not in reg._sessions and len(reg) == 1  # purged on create
    reg._sessions[fresh.session_id].expires_at = datetime.now(UTC) + timedelta(days=1)
    _, _, rotated = reg.rotate(fresh.refresh_token)
    assert rotated.expires_at > datetime.now(UTC) + timedelta(days=13)


def test_registry_rebind_and_revoke():
    reg = SessionRegistry(refresh_days=14)
    issued = reg.create(1, remember_me=False, stamp_fingerprint="old")
    reg.rebind_stamp(issued.session_id, "new")
    assert reg._sessions[issued.session_id].stamp_fingerprint == "new"
    reg.revoke(issued.session_id)
    reg.revoke("unknown")
    reg.rebind_stamp("unknown", "x")
    assert not reg.is_active(issued.session_id, 1)


# ── login rules ─────────────────────────────────────────────────────────────


def test_lockout_rule():
    now = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    u = user(lockout_end_date_utc=datetime(2026, 10, 23, 12, 0))
    assert is_locked_out(u, now)  # >= now
    u.lockout_end_date_utc = datetime(2026, 10, 23, 11, 59)
    assert not is_locked_out(u, now)
    u.lockout_end_date_utc = None
    assert not is_locked_out(u, now)
    u.lockout_end_date_utc, u.lockout_enabled = datetime(2027, 1, 1), False
    assert not is_locked_out(u, now)


def test_two_factor_needs_a_confirmed_channel():
    assert not requires_two_factor(user(two_factor_enabled=False))
    assert requires_two_factor(user(two_factor_enabled=True, email_confirmed=True))
    assert requires_two_factor(
        user(two_factor_enabled=True, email_confirmed=False, phone_number_confirmed=True)
    )
    assert not requires_two_factor(
        user(two_factor_enabled=True, email_confirmed=False, phone_number_confirmed=False)
    )


# ── request info ────────────────────────────────────────────────────────────


def _request(headers: dict[str, str], client=("192.0.2.1", 1234)) -> Request:
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": client,
    }
    return Request(scope)


def test_client_ip_rules():
    assert client_ip(_request({})) == "192.0.2.1"
    assert client_ip(_request({"X-Forwarded-For": "198.51.100.7, 10.0.0.1"})) == "198.51.100.7"
    assert client_ip(_request({}, client=None)) == ""


@pytest.mark.parametrize(
    ("ua", "expected"),
    [
        ("Mozilla/5.0 (Windows NT 10.0) Chrome/118.0.5993.88 Safari/537.36", ("Chrome", "118.0")),
        ("Mozilla/5.0 Chrome/118.0 Safari/537.36 Edg/118.0.2088.69", ("Edge", "118.0")),
        ("Mozilla/5.0 (X11; Linux) Gecko/20100101 Firefox/119.0", ("Firefox", "119.0")),
        ("Mozilla/5.0 (Macintosh) Version/17.1 Safari/605.1.15", ("Safari", "17.1")),
        (
            "Mozilla/5.0 (compatible; MSIE 10.0; Windows NT 6.1; Trident/6.0)",
            ("InternetExplorer", "10.0"),
        ),
        (None, ("Unknown", "0.0")),
    ],
)
def test_browser_parser(ua, expected):
    assert browser(ua) == expected


async def test_web_request_identification_shape():
    text = await web_request_identification(_request({"User-Agent": "Firefox/119.0"}, client=None))
    assert (
        text == "Machine Name=;IP Address=;Logon User=;Browser Name=Firefox;Browser Version=119.0"
    )


def test_one_line_pem_with_escaped_newlines_is_accepted():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    one_line = pem.replace("\n", "\\n")
    service = TokenService(
        Settings(ENVIRONMENT="uat", JWT_PRIVATE_KEY_PEM=one_line, OTP_SIGNING_KEY="k" * 32)
    )
    token, _ = service.create_access_token(5, "s")
    assert service.decode_access_token(token).user_id == 5
