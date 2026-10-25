"""
Signed tokens for P1-M2 (01d A1-A9).

1. **Access token**: RS256 JWT, `ACCESS_TOKEN_MINUTES` (30) = legacy 30-minute
   SecurityStamp re-validation [Code `App_Start/Startup.Auth.cs` validateInterval 30 min].
   Claims: iss, aud, sub (user id), sid (session id), iat, exp, jti, typ="access".
   Personal data is never put in a token.
2. **OTP challenge** (`challengeId`) and **reset ticket** (`resetTicket`): HS256 JWT signed
   with `OTP_SIGNING_KEY`, bound to the user id and a fingerprint of the user's
   SecurityStamp. Legacy password-reset tokens (`DataProtectorTokenProvider`) are bound to
   the SecurityStamp the same way, so a login, a password change or a completed reset
   invalidates every outstanding challenge and ticket — on any API instance, without a table.
3. **OTP**: 6 digits derived from the challenge (HMAC-SHA1 + RFC 4226 dynamic truncation,
   the same construction as legacy `OtpAuthenticator`). The server stores nothing; the OTP is
   only ever written to `AlertQueues` (D4) and never returned or logged.

Keys: from settings; only ENVIRONMENT=local/test may run with keys generated at start-up.
"""

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import secrets
from typing import Any
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt

from app.core.config import Settings
from app.core.exceptions import CredentialsError, TokenExpiredError


ACCESS = "access"
OTP_CHALLENGE = "otp_challenge"
RESET_TICKET = "reset_ticket"
_OTP_AUDIENCE_SUFFIX = "-password-reset"
OTP_DIGITS = 6


class InvalidSignedTokenError(Exception):
    """Challenge/ticket missing, malformed, wrong signature, wrong purpose or expired."""


@dataclass(frozen=True)
class AccessClaims:
    user_id: int
    session_id: str
    expires_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


class TokenService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        if settings.JWT_PRIVATE_KEY_PEM is not None:
            # Accept a one-line value with literal "\n" (env var set outside .env).
            pem = settings.JWT_PRIVATE_KEY_PEM.get_secret_value().replace("\\n", "\n").encode()
            private_key = serialization.load_pem_private_key(pem, password=None)
        elif settings.allows_ephemeral_keys:
            private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        else:  # pragma: no cover - blocked by validate_auth_config at start-up
            raise RuntimeError("JWT_PRIVATE_KEY_PEM is required")
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise RuntimeError("JWT_PRIVATE_KEY_PEM must be an RSA private key")
        self._private_key = private_key
        self._public_key = private_key.public_key()

        if settings.OTP_SIGNING_KEY is not None:
            self._otp_key = settings.OTP_SIGNING_KEY.get_secret_value().encode("utf-8")
        elif settings.allows_ephemeral_keys:
            self._otp_key = secrets.token_bytes(32)
        else:  # pragma: no cover - blocked by validate_auth_config at start-up
            raise RuntimeError("OTP_SIGNING_KEY is required")

    # ── access tokens ───────────────────────────────────────────────────────
    def create_access_token(self, user_id: int, session_id: str) -> tuple[str, datetime]:
        now = _now()
        exp = now + timedelta(minutes=self._settings.ACCESS_TOKEN_MINUTES)
        payload = {
            "iss": self._settings.JWT_ISSUER,
            "aud": self._settings.JWT_AUDIENCE,
            "sub": str(user_id),
            "sid": session_id,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "jti": uuid.uuid4().hex,
            "typ": ACCESS,
        }
        return jwt.encode(payload, self._private_key, algorithm="RS256"), exp.replace(microsecond=0)

    def decode_access_token(self, token: str) -> AccessClaims:
        try:
            data = jwt.decode(
                token,
                self._public_key,
                algorithms=["RS256"],
                audience=self._settings.JWT_AUDIENCE,
                issuer=self._settings.JWT_ISSUER,
                options={"require": ["exp", "iat", "sub", "sid", "typ", "jti"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenExpiredError("Access token expired") from exc
        except jwt.PyJWTError as exc:
            raise CredentialsError("Invalid access token") from exc
        if data.get("typ") != ACCESS:
            raise CredentialsError("Invalid access token")
        try:
            user_id = int(data["sub"])
        except (TypeError, ValueError) as exc:
            raise CredentialsError("Invalid access token") from exc
        return AccessClaims(
            user_id=user_id,
            session_id=str(data["sid"]),
            expires_at=datetime.fromtimestamp(data["exp"], UTC),
        )

    # ── SecurityStamp fingerprint ───────────────────────────────────────────
    def stamp_fingerprint(self, security_stamp: str | None) -> str:
        """Keyed fingerprint, so tokens never carry the stamp itself."""
        digest = hmac.new(
            self._otp_key, b"stamp|" + (security_stamp or "").encode("utf-8"), hashlib.sha256
        ).digest()
        return base64.urlsafe_b64encode(digest[:18]).decode("ascii")

    # ── OTP challenge / reset ticket ────────────────────────────────────────
    def _sign(self, typ: str, user_id: int, security_stamp: str | None, minutes: int) -> str:
        now = _now()
        payload = {
            "iss": self._settings.JWT_ISSUER,
            "aud": self._settings.JWT_AUDIENCE + _OTP_AUDIENCE_SUFFIX,
            "sub": str(user_id),
            "sst": self.stamp_fingerprint(security_stamp),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=minutes)).timestamp()),
            "jti": uuid.uuid4().hex,
            "typ": typ,
        }
        return jwt.encode(payload, self._otp_key, algorithm="HS256")

    def _verify(self, token: str | None, typ: str) -> dict[str, Any]:
        if not token:
            raise InvalidSignedTokenError("missing")
        try:
            data = jwt.decode(
                token,
                self._otp_key,
                algorithms=["HS256"],
                audience=self._settings.JWT_AUDIENCE + _OTP_AUDIENCE_SUFFIX,
                issuer=self._settings.JWT_ISSUER,
                options={"require": ["exp", "sub", "sst", "jti", "typ"]},
            )
        except jwt.PyJWTError as exc:
            raise InvalidSignedTokenError(type(exc).__name__) from exc
        if data.get("typ") != typ:
            raise InvalidSignedTokenError("wrong purpose")
        return data

    def create_otp_challenge(self, user_id: int, security_stamp: str | None) -> tuple[str, str]:
        """Returns (challengeId, otp). The OTP goes to AlertQueues only."""
        challenge = self._sign(
            OTP_CHALLENGE, user_id, security_stamp, self._settings.OTP_TTL_MINUTES
        )
        return challenge, self._otp_for(self._verify(challenge, OTP_CHALLENGE)["jti"])

    def verify_otp(
        self, challenge: str | None, otp: str | None, user_id: int, security_stamp: str | None
    ) -> bool:
        try:
            data = self._verify(challenge, OTP_CHALLENGE)
        except InvalidSignedTokenError:
            return False
        if data["sub"] != str(user_id):
            return False
        if not hmac.compare_digest(data["sst"], self.stamp_fingerprint(security_stamp)):
            return False
        if not otp or len(otp) != OTP_DIGITS:
            return False
        return hmac.compare_digest(self._otp_for(data["jti"]), otp)

    def create_reset_ticket(self, user_id: int, security_stamp: str | None) -> str:
        return self._sign(
            RESET_TICKET, user_id, security_stamp, self._settings.RESET_TICKET_TTL_MINUTES
        )

    def verify_reset_ticket(
        self, ticket: str | None, user_id: int, security_stamp: str | None
    ) -> bool:
        try:
            data = self._verify(ticket, RESET_TICKET)
        except InvalidSignedTokenError:
            return False
        if data["sub"] != str(user_id):
            return False
        return hmac.compare_digest(data["sst"], self.stamp_fingerprint(security_stamp))

    def _otp_for(self, challenge_id: str) -> str:
        digest = hmac.new(self._otp_key, b"otp|" + challenge_id.encode(), hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        binary = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
        return str(binary % 10**OTP_DIGITS).zfill(OTP_DIGITS)
