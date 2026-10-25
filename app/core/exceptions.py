"""
Application errors. Every error leaves the API as
`{"errorCode": ..., "message": ..., "errors"?: [...]}` (plan §7, same as ems-mdp-backend).
Raise these from services; never raise raw HTTPException.
"""

from typing import Any


class AppBaseError(Exception):
    status_code: int = 500
    detail: str = "Internal server error"
    error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        detail: str | None = None,
        status_code: int | None = None,
        error_code: str | None = None,
        errors: list[Any] | None = None,
    ):
        super().__init__(detail or self.detail)
        if detail:
            self.detail = detail
        if status_code:
            self.status_code = status_code
        if error_code:
            self.error_code = error_code
        self.errors: list[Any] = errors or []


class BadRequestError(AppBaseError):
    status_code = 400
    detail = "Bad request"
    error_code = "BAD_REQUEST"


class CredentialsError(AppBaseError):
    status_code = 401
    detail = "Could not validate credentials"
    error_code = "UNAUTHORIZED"


class TokenExpiredError(CredentialsError):
    detail = "Token has expired"
    error_code = "TOKEN_EXPIRED"


class ForbiddenError(AppBaseError):
    status_code = 403
    detail = "Not authorized for this action"
    error_code = "FORBIDDEN"


class NotFoundError(AppBaseError):
    status_code = 404
    detail = "Resource not found"
    error_code = "NOT_FOUND"


class ConflictError(AppBaseError):
    status_code = 409
    detail = "Resource already exists"
    error_code = "CONFLICT"


class ValidationError(AppBaseError):
    status_code = 422
    detail = "Validation error"
    error_code = "VALIDATION_ERROR"


class DatabaseError(AppBaseError):
    status_code = 500
    detail = "A database error occurred"
    error_code = "DATABASE_ERROR"


class ServiceUnavailableError(AppBaseError):
    status_code = 503
    detail = "Service unavailable"
    error_code = "SERVICE_UNAVAILABLE"
