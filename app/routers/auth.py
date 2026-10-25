"""`/auth/*` — login and own account (01d §2.1, A1-A10). Thin: services do the work."""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_reader_db, get_writer_db
from app.core.identity_password import LEGACY_POLICY
from app.core.request_info import client_ip, web_request_identification
from app.core.security import AuthRuntime, Principal, get_auth_runtime, get_current_principal
from app.schemas.auth import (
    ChallengeResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    MeResponse,
    PasswordPolicyResponse,
    RefreshRequest,
    ResetPasswordRequest,
    ResetTicketResponse,
    TokenPair,
    UpdateProfileRequest,
    VerifyOtpRequest,
)
from app.schemas.common import ErrorResponse
from app.services import auth_service, password_reset, profile


router = APIRouter(prefix="/auth", tags=["Authentication"])

_ERRORS = {
    400: {"model": ErrorResponse},
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


def _runtime() -> AuthRuntime:
    return get_auth_runtime()


@router.post("/login", response_model=LoginResponse, responses=_ERRORS, summary="A1 Log in")
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_writer_db),
    settings: Settings = Depends(get_settings),
    runtime: AuthRuntime = Depends(_runtime),
) -> LoginResponse:
    meta = auth_service.RequestMeta(
        ip=client_ip(request), web_request_identification=await web_request_identification(request)
    )
    return await auth_service.login(db, settings, runtime, body, meta)


@router.post(
    "/refresh-token", response_model=TokenPair, responses=_ERRORS, summary="A2 Refresh tokens"
)
async def refresh_token(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_reader_db),
    runtime: AuthRuntime = Depends(_runtime),
) -> TokenPair:
    return await auth_service.refresh(db, runtime, body.refresh_token)


@router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, responses=_ERRORS, summary="A3 Log out"
)
async def logout(
    principal: Principal = Depends(get_current_principal),
    runtime: AuthRuntime = Depends(_runtime),
) -> Response:
    auth_service.logout(runtime, principal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeResponse, responses=_ERRORS, summary="A4 My account")
async def get_me(
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_reader_db),
) -> MeResponse:
    return await profile.get_me(db, principal)


@router.put(
    "/me", response_model=MeResponse, responses=_ERRORS, summary="A5 Update my e-mail/phone"
)
async def update_me(
    body: UpdateProfileRequest,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_writer_db),
) -> MeResponse:
    return await profile.update_me(db, principal, body)


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ERRORS,
    summary="A6 Change my password",
)
async def change_password(
    body: ChangePasswordRequest,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_writer_db),
    runtime: AuthRuntime = Depends(_runtime),
) -> Response:
    await profile.change_password(db, runtime, principal, body)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/forgot-password",
    response_model=ChallengeResponse,
    responses={**_ERRORS, 404: {"model": ErrorResponse}},
    summary="A7 Forgot password (queues the OTP)",
)
async def forgot_password(
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_writer_db),
    settings: Settings = Depends(get_settings),
    runtime: AuthRuntime = Depends(_runtime),
) -> ChallengeResponse:
    return await password_reset.forgot_password(db, settings, runtime, body)


@router.post(
    "/verify-otp", response_model=ResetTicketResponse, responses=_ERRORS, summary="A8 Verify OTP"
)
async def verify_otp(
    body: VerifyOtpRequest,
    db: AsyncSession = Depends(get_reader_db),
    runtime: AuthRuntime = Depends(_runtime),
) -> ResetTicketResponse:
    return await password_reset.verify_otp(db, runtime, body)


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ERRORS,
    summary="A9 Reset password with the reset ticket",
)
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_writer_db),
    runtime: AuthRuntime = Depends(_runtime),
) -> Response:
    await password_reset.reset_password(db, runtime, body)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/password-policy", response_model=PasswordPolicyResponse, summary="A10 Password policy"
)
async def password_policy() -> PasswordPolicyResponse:
    return PasswordPolicyResponse(**LEGACY_POLICY.model_dump())
