"""
Authentication plumbing shared by routers (P1-M2).

* `get_auth_runtime()` — one `TokenService` + one `SessionRegistry` per process.
* `get_current_principal` — FastAPI dependency: Bearer access token → `Principal`.
  Rejects expired/invalid tokens and tokens whose session was revoked (logout, replay,
  restart). Shown in Swagger as the "Authorize" (HTTP bearer) button.

Permission guards (S4: `require_permission`, Super Admin area, …) arrive in P1-M3.
"""

from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.core.exceptions import CredentialsError
from app.core.session_registry import SessionRegistry
from app.core.tokens import TokenService


@dataclass(frozen=True)
class AuthRuntime:
    tokens: TokenService
    sessions: SessionRegistry


@lru_cache
def get_auth_runtime() -> AuthRuntime:
    settings = get_settings()
    return AuthRuntime(TokenService(settings), SessionRegistry(settings.REFRESH_TOKEN_DAYS))


@dataclass(frozen=True)
class Principal:
    user_id: int
    session_id: str


bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="bearer",
    description="Paste the `accessToken` from `POST /auth/login`.",
)


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise CredentialsError("Not authenticated")
    runtime = get_auth_runtime()
    claims = runtime.tokens.decode_access_token(credentials.credentials)
    if not runtime.sessions.is_active(claims.session_id, claims.user_id):
        raise CredentialsError("Session ended. Please log in again.", error_code="SESSION_ENDED")
    return Principal(user_id=claims.user_id, session_id=claims.session_id)
