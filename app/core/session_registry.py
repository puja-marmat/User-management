"""
In-memory refresh-token sessions (P1-M2, 01d D1; approved by the user 2026-10-23).

Why in memory: Phase 1 allows no new tables (U01 DEC-34) and refresh-token rotation with
replay detection needs server state. Accepted limitation, documented in
`docs/UAT-P1-M2.md` and 00a §0:

* **run ONE API instance** in Phase 1 (sessions are not shared between processes);
* a restart signs everyone out (fails closed: unknown session = invalid).

Rules:
* Refresh token = ``<sessionId>.<secret>``; only SHA-256 of the secret is kept. Tokens are
  never logged or persisted.
* Every refresh rotates the secret and slides the expiry (`REFRESH_TOKEN_DAYS`, 14 = OWIN
  default ticket, sliding). The same lifetime applies with and without "remember me"
  (user decision); without it the client keeps the token in sessionStorage, so it dies
  with the browser tab — the server cannot see a browser close.
* Presenting an already-rotated secret (**replay**) revokes the whole session.
* The session is bound to a fingerprint of the user's SecurityStamp; the caller checks it
  on refresh (legacy `SecurityStampValidator`).
* Logout revokes the session; access tokens carry the session id and are rejected
  once it is revoked.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import hashlib
import hmac
import secrets
import threading


class RefreshOutcome(StrEnum):
    OK = "ok"
    INVALID = "invalid"  # malformed or unknown session (e.g. after a restart)
    EXPIRED = "expired"
    REVOKED = "revoked"
    REPLAYED = "replayed"  # rotated secret presented again → session revoked


@dataclass
class Session:
    session_id: str
    user_id: int
    remember_me: bool
    stamp_fingerprint: str
    secret_hash: bytes
    expires_at: datetime
    revoked: bool = False
    used_hashes: set[bytes] = field(default_factory=set)


@dataclass(frozen=True)
class IssuedRefresh:
    session_id: str
    refresh_token: str
    expires_at: datetime


def _hash(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("ascii")).digest()


def _now() -> datetime:
    return datetime.now(UTC)


class SessionRegistry:
    def __init__(self, refresh_days: int) -> None:
        self._lifetime = timedelta(days=refresh_days)
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._sessions)

    def create(self, user_id: int, remember_me: bool, stamp_fingerprint: str) -> IssuedRefresh:
        session_id = secrets.token_urlsafe(16)
        secret = secrets.token_urlsafe(32)
        expires = _now() + self._lifetime
        with self._lock:
            self._purge_locked()
            self._sessions[session_id] = Session(
                session_id=session_id,
                user_id=user_id,
                remember_me=remember_me,
                stamp_fingerprint=stamp_fingerprint,
                secret_hash=_hash(secret),
                expires_at=expires,
            )
        return IssuedRefresh(session_id, f"{session_id}.{secret}", expires)

    def rotate(
        self, refresh_token: str | None
    ) -> tuple[RefreshOutcome, Session | None, IssuedRefresh | None]:
        """Check a refresh token and, when valid, rotate it. Never raises on bad input."""
        session_id, _, secret = (refresh_token or "").partition(".")
        if not session_id or not secret or not secret.isascii():
            return RefreshOutcome.INVALID, None, None
        presented = _hash(secret)
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return RefreshOutcome.INVALID, None, None
            if session.revoked:
                return RefreshOutcome.REVOKED, session, None
            if _now() >= session.expires_at:
                session.revoked = True
                return RefreshOutcome.EXPIRED, session, None
            if not hmac.compare_digest(presented, session.secret_hash):
                if presented in session.used_hashes:
                    session.revoked = True
                    return RefreshOutcome.REPLAYED, session, None
                return RefreshOutcome.INVALID, None, None
            new_secret = secrets.token_urlsafe(32)
            session.used_hashes.add(session.secret_hash)
            session.secret_hash = _hash(new_secret)
            session.expires_at = _now() + self._lifetime
            issued = IssuedRefresh(session_id, f"{session_id}.{new_secret}", session.expires_at)
            return RefreshOutcome.OK, session, issued

    def is_active(self, session_id: str, user_id: int) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            return (
                session is not None
                and not session.revoked
                and session.user_id == user_id
                and _now() < session.expires_at
            )

    def rebind_stamp(self, session_id: str, stamp_fingerprint: str) -> None:
        """Keep the caller's own session after its password change (legacy re-sign-in)."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None and not session.revoked:
                session.stamp_fingerprint = stamp_fingerprint

    def revoke(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.revoked = True

    def _purge_locked(self) -> None:
        now = _now()
        for sid in [s.session_id for s in self._sessions.values() if s.expires_at <= now]:
            del self._sessions[sid]
