"""
Forgot password → OTP → reset (01d A7-A9), with the F1 fix.

Legacy [Code `CrystalPower.Web/Controllers/AccountController.cs`]:
* ForgotPassword POST (:385-436): `FindByName(UserName)`; checks in this order, each with
  its own message (F14 kept): no account, disabled, e-mail not confirmed, no mobile number.
  Then reset token + OTP (`OtpAuthenticator`, 6 digits) and a ForgotPasswordOTP alert;
  the OTPConfirmation page carried the reset **token** to the browser (**F1**).
* ConfirmOTP (:442-466): OTP checked against that token; failure → "Invalid/Expired OTP.
  Please try again."; success → ResetPassword page with the token.
* ResetPassword POST (:491-512): validation (`ResetPasswordViewModel`); unknown user →
  success page (does not reveal the user); `ResetPasswordAsync` → "Invalid token." on a bad
  token; then policy, new v2 hash, new SecurityStamp.

New flow (F1): `forgot-password` returns only a signed `challengeId`; the OTP goes to
`AlertQueues` (D4) and nowhere else; `verify-otp` returns a short-lived `resetTicket`;
`reset-password` accepts only that ticket. Challenge and ticket are bound to the user and
to the SecurityStamp, so a completed reset (or any login, as legacy) kills them all:
a ticket can never be used twice. Lifetimes: `OTP_TTL_MINUTES` / `RESET_TICKET_TTL_MINUTES`
(10 min, approved 2026-10-23). No attempt limit (legacy has none; lockout = IMP-01).

Tables: R ApplicationUsers, UserSites, Alerts, SiteAlerts · W AlertQueues (A7),
ApplicationUsers (A9).
"""

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import Settings
from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.core.identity_password import hash_password, new_security_stamp, password_policy_errors
from app.core.security import AuthRuntime
from app.schemas.auth import (
    ChallengeResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    ResetTicketResponse,
    VerifyOtpRequest,
)
from app.services.alert_queue_service import queue_forgot_password_otp
from app.services.legacy_validation import FieldErrors
from app.services.user_context import find_user_by_name, first_user_site_id


log = structlog.get_logger(__name__)

NO_ACCOUNT = "No Account was found by this username."
NOT_ENABLED = "Your account is not enabled. Please contact administrator."
EMAIL_NOT_VERIFIED = "Account Email is not verified."
NO_MOBILE = " No Mobile Number registerd for the User."  # legacy text, leading space kept
INVALID_OTP = "Invalid/Expired OTP. Please try again."
INVALID_TOKEN = "Invalid token."  # noqa: S105 - legacy message
CONFIRM_MISMATCH = "The password and confirmation password do not match."
STATUS_DISABLED = 0


async def forgot_password(
    session: AsyncSession,
    settings: Settings,
    runtime: AuthRuntime,
    body: ForgotPasswordRequest,
) -> ChallengeResponse:
    errors = FieldErrors()
    errors.required("userName", "User Name", body.user_name)
    errors.raise_if_any()

    user = await find_user_by_name(session, body.user_name)
    if user is None:
        raise NotFoundError(NO_ACCOUNT, error_code="ACCOUNT_NOT_FOUND")
    if user.status_id == STATUS_DISABLED:
        raise ForbiddenError(NOT_ENABLED, error_code="ACCOUNT_DISABLED")
    if not user.email_confirmed:
        raise BadRequestError(EMAIL_NOT_VERIFIED, error_code="EMAIL_NOT_VERIFIED")
    if not user.phone_number:
        raise BadRequestError(NO_MOBILE, error_code="NO_MOBILE_NUMBER")

    challenge, otp = runtime.tokens.create_otp_challenge(user.id, user.security_stamp)
    site_id = await first_user_site_id(session, user.id)
    outcome = await queue_forgot_password_otp(session, settings, user, otp, site_id)
    await session.commit()
    log.info("forgot_password_otp", user_id=user.id, alert=outcome.value)
    return ChallengeResponse(challenge_id=challenge)


async def verify_otp(
    session: AsyncSession, runtime: AuthRuntime, body: VerifyOtpRequest
) -> ResetTicketResponse:
    user = await find_user_by_name(session, body.user_name)
    if user is None or not runtime.tokens.verify_otp(
        body.challenge_id, body.otp, user.id, user.security_stamp
    ):
        log.info("otp_rejected", user_id=user.id if user else None)
        raise BadRequestError(INVALID_OTP, error_code="INVALID_OTP")
    log.info("otp_verified", user_id=user.id)
    return ResetTicketResponse(
        reset_ticket=runtime.tokens.create_reset_ticket(user.id, user.security_stamp)
    )


async def reset_password(
    session: AsyncSession, runtime: AuthRuntime, body: ResetPasswordRequest
) -> None:
    errors = FieldErrors()
    errors.required("userName", "User Name", body.user_name)
    if errors.required("password", "Password", body.password):
        errors.length_between("password", "Password", body.password or "", 6, 100)
    if (body.confirm_password or None) != (body.password or None):
        errors.add("confirmPassword", CONFIRM_MISMATCH)
    errors.raise_if_any()

    user = await find_user_by_name(session, body.user_name)
    if user is None:
        log.info("password_reset_unknown_user")
        return  # legacy: "Don't reveal that the user does not exist"
    if not runtime.tokens.verify_reset_ticket(body.reset_ticket, user.id, user.security_stamp):
        log.info("password_reset_rejected", user_id=user.id)
        raise BadRequestError(INVALID_TOKEN, error_code="INVALID_TOKEN")
    policy = password_policy_errors(body.password)
    if policy:
        raise BadRequestError(policy, error_code="PASSWORD_POLICY")

    user.password_hash = hash_password(body.password or "")
    user.security_stamp = new_security_stamp()
    await session.commit()
    log.info("password_reset", user_id=user.id)
