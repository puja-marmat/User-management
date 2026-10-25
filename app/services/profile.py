"""
Own account (01d A4-A6).

* A4 `GET /auth/me`: the user's profile + claims-equivalent context.
* A5 `PUT /auth/me` — legacy `Account/MyAccount` POST [Code `AccountController.cs:738-772`]:
  site admins are sent back to Home (→ 403 here); validation from `UserProfileViewModel`
  (Email required; Phone No. required, max 10, [Phone], `^[789]\\d{9}$` "Not a valid Phone
  number"); **only Email and PhoneNumber are written** (no FullName, no UpdatedDate — legacy
  `AddOrUpdate` copies unchanged values for the rest). Legacy takes the user id from the
  posted form; here it is always the signed-in user (own account only, D1 default (b)).
* A6 `POST /auth/change-password` — legacy `Account/ChangePassword` POST
  [Code `AccountController.cs:776-804`] → Identity 2 `ChangePasswordAsync`: validation from
  `IdentitySample.Models.ChangePasswordViewModel`; wrong old password → "Incorrect
  password."; password policy; new v2 hash; new SecurityStamp. Other sessions end at their
  next refresh (≤ 30 min, like legacy); the caller's own session is kept (legacy
  `Manage/ChangePassword` signs the user in again).

Tables: R/W ApplicationUsers only.
"""

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.exceptions import BadRequestError, CredentialsError, ForbiddenError
from app.core.identity_password import (
    hash_password,
    new_security_stamp,
    password_policy_errors,
    verify_password,
)
from app.core.security import AuthRuntime, Principal
from app.models.legacy import ApplicationUser
from app.schemas.auth import (
    ChangePasswordRequest,
    MeResponse,
    UpdateProfileRequest,
    UserProfile,
)
from app.services.legacy_validation import LEGACY_MOBILE, FieldErrors, is_phone
from app.services.user_context import UserContext, build_user_context


log = structlog.get_logger(__name__)

INCORRECT_PASSWORD = "Incorrect password."  # noqa: S105 - legacy message
CONFIRM_MISMATCH_NEW = "The new password and confirmation password do not match."


def to_me_response(ctx: UserContext, current_site_id: int | None) -> MeResponse:
    u = ctx.user
    return MeResponse(
        user=UserProfile(
            id=u.id,
            guid=u.guid,
            user_name=u.user_name,
            full_name=u.full_name,
            email=u.email,
            phone_number=u.phone_number,
            status_id=u.status_id,
            consumer_no=u.consumer_no,
        ),
        permissions=ctx.permissions,
        flags=ctx.flags,
        sites=ctx.sites,
        tower_ids=ctx.tower_ids,
        current_site_id=current_site_id,
    )


async def _load(session: AsyncSession, principal: Principal) -> ApplicationUser:
    user = await session.get(ApplicationUser, principal.user_id)
    if user is None:
        raise CredentialsError("Session ended. Please log in again.", error_code="SESSION_ENDED")
    return user


async def get_me(session: AsyncSession, principal: Principal) -> MeResponse:
    ctx = await build_user_context(session, await _load(session, principal))
    # Site switching (X-Site-Id, F4) arrives in P1-M3; until then the legacy default site.
    return to_me_response(ctx, ctx.default_site_id)


async def update_me(
    session: AsyncSession, principal: Principal, body: UpdateProfileRequest
) -> MeResponse:
    user = await _load(session, principal)
    ctx = await build_user_context(session, user)
    if ctx.flags.is_site_admin:
        raise ForbiddenError("Profile editing is not available for site administrators.")

    errors = FieldErrors()
    errors.required("email", "Email", body.email)
    if errors.required("phoneNumber", "Phone No.", body.phone_number):
        phone = body.phone_number or ""
        errors.max_length("phoneNumber", "Phone No.", phone, 10)
        if not is_phone(phone):
            errors.add("phoneNumber", "The Phone No. field is not a valid phone number.")
        if not LEGACY_MOBILE.match(phone):
            errors.add("phoneNumber", "Not a valid Phone number")
    errors.raise_if_any()

    user.email = body.email
    user.phone_number = body.phone_number
    await session.commit()
    log.info("profile_updated", user_id=user.id)
    return to_me_response(ctx, ctx.default_site_id)


async def change_password(
    session: AsyncSession,
    runtime: AuthRuntime,
    principal: Principal,
    body: ChangePasswordRequest,
) -> None:
    errors = FieldErrors()
    errors.required("oldPassword", "Current password", body.old_password)
    if errors.required("newPassword", "New password", body.new_password):
        errors.length_between("newPassword", "New password", body.new_password or "", 6, 100)
    if (body.confirm_password or None) != (body.new_password or None):
        errors.add("confirmPassword", CONFIRM_MISMATCH_NEW)
    errors.raise_if_any()

    user = await _load(session, principal)
    if not verify_password(user.password_hash, body.old_password):
        raise BadRequestError(INCORRECT_PASSWORD, error_code="INCORRECT_PASSWORD")
    policy = password_policy_errors(body.new_password)
    if policy:
        raise BadRequestError(policy, error_code="PASSWORD_POLICY")

    user.password_hash = hash_password(body.new_password or "")
    user.security_stamp = new_security_stamp()
    await session.commit()
    runtime.sessions.rebind_stamp(
        principal.session_id, runtime.tokens.stamp_fingerprint(user.security_stamp)
    )
    log.info("password_changed", user_id=user.id)
