"""
Request/response shapes for `/auth/*` (01d §2.1, A1-A10).

Request fields are deliberately optional strings: the services apply the legacy
DataAnnotations rules themselves so the error messages are the legacy ones
(e.g. "The Email field is required."). Secrets (passwords, OTP, tokens) are never
echoed back or logged.
"""

from datetime import datetime
import uuid

from pydantic import Field

from app.core.identity_password import PasswordPolicy
from app.schemas.common import CamelModel


# ── requests ────────────────────────────────────────────────────────────────


class LoginRequest(CamelModel):
    user_name: str | None = Field(
        default=None, description="User name or e-mail (legacy field `Email`)."
    )
    password: str | None = None
    remember_me: bool = False
    meter_no: str | None = Field(
        default=None, description="Optional meter number (end-user deep link, D5)."
    )


class RefreshRequest(CamelModel):
    refresh_token: str | None = None


class UpdateProfileRequest(CamelModel):
    email: str | None = None
    phone_number: str | None = None


class ChangePasswordRequest(CamelModel):
    old_password: str | None = None
    new_password: str | None = None
    confirm_password: str | None = None


class ForgotPasswordRequest(CamelModel):
    user_name: str | None = None


class VerifyOtpRequest(CamelModel):
    user_name: str | None = None
    challenge_id: str | None = None
    otp: str | None = None


class ResetPasswordRequest(CamelModel):
    user_name: str | None = None
    reset_ticket: str | None = None
    password: str | None = None
    confirm_password: str | None = None


# ── responses ───────────────────────────────────────────────────────────────


class Flags(CamelModel):
    is_super_admin: bool = False
    is_system_admin: bool = False
    is_site_admin: bool = False
    is_end_user: bool = False
    is_sub_division: bool = False


class SiteRef(CamelModel):
    id: int
    name: str


class UserProfile(CamelModel):
    id: int
    guid: uuid.UUID
    user_name: str | None
    full_name: str | None
    email: str | None
    phone_number: str | None
    status_id: int
    consumer_no: str | None


class MeResponse(CamelModel):
    user: UserProfile
    permissions: list[str]
    flags: Flags
    sites: list[SiteRef]
    tower_ids: list[int]
    current_site_id: int | None


class TokenPair(CamelModel):
    access_token: str
    token_type: str = "Bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    remember_me: bool = Field(
        description="false: keep the refresh token in sessionStorage (browser-session login)."
    )


class LoginResponse(TokenPair, MeResponse):
    pass


class ChallengeResponse(CamelModel):
    challenge_id: str


class ResetTicketResponse(CamelModel):
    reset_ticket: str


class PasswordPolicyResponse(PasswordPolicy):
    model_config = CamelModel.model_config
