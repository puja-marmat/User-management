"""
FastAPI application factory.

The API never runs database migrations at start-up (plan §4.3): migrations run as a
separate one-off `migrate` container job before the API rolls out.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
import structlog

from app.api_router import router as api_router
from app.core.config import (
    get_settings,
    validate_auth_config,
    validate_phase1_config,
    validate_production_config,
)
from app.core.database import dispose_engines
from app.core.exceptions import AppBaseError
from app.middleware.request_context import RequestContextMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.telemetry.logging import configure_logging


log = structlog.get_logger(__name__)

_DESCRIPTION = """
# Prime MDM API

Backend for the SAV MDM migration (CrystalPower → EMS). First feature: U01 User
Management, Phase 1 lift and shift on the existing `sav_uat` tables.

* Authentication: `POST /auth/login`, then click **Authorize** and paste the `accessToken`.

* No version prefix; camelCase JSON.
* Errors: `{ "errorCode": "...", "message": "...", "errors"?: [...] }`.
* Pagination: `{ data, totalElements, totalPages, page, size }`.
* Docs are disabled when `ENVIRONMENT=prod`.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    validate_production_config(settings)
    validate_phase1_config(settings)
    validate_auth_config(settings)
    log.info("startup", version=settings.APP_VERSION)
    try:
        yield
    finally:
        await dispose_engines()
        log.info("shutdown")


def _error_body(code: str, message: str, errors: list | None = None) -> dict:
    body: dict = {"errorCode": code, "message": message}
    if errors:
        body["errors"] = errors
    return body


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    show_docs = not settings.is_production

    app = FastAPI(
        title="Prime MDM API",
        description=_DESCRIPTION,
        version=settings.APP_VERSION,
        lifespan=lifespan,
        docs_url="/docs" if show_docs else None,
        redoc_url="/redoc" if show_docs else None,
        openapi_url="/openapi.json" if show_docs else None,
    )

    # ── Middleware (last added runs first) ───────────────────────────────────
    app.add_middleware(GZipMiddleware, minimum_size=1_000)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-Id", "X-Site-Id", "X-Tenant"],
        expose_headers=[
            "Content-Disposition",
            "X-Request-Id",
            "X-Duration-Ms",
            "x-service-version",
            "X-Token-Expires-At",
            "X-Session-Expired",
            "X-Token-Expired",
        ],
    )
    app.add_middleware(RequestContextMiddleware)

    # ── Error handlers: one envelope for everything ──────────────────────────
    @app.exception_handler(AppBaseError)
    async def _app_error(_: Request, exc: AppBaseError) -> JSONResponse:
        headers = None
        if exc.error_code == "TOKEN_EXPIRED":
            headers = {"X-Token-Expired": "true"}
        elif exc.error_code == "SESSION_ENDED":
            headers = {"X-Session-Expired": "true"}
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.error_code, exc.detail, exc.errors),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422, content=_error_body("VALIDATION_ERROR", "Validation error", errors)
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(code, str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_exception", exc_type=type(exc).__name__, path=request.url.path)
        return JSONResponse(
            status_code=500, content=_error_body("INTERNAL_ERROR", "An internal error occurred")
        )

    app.include_router(api_router)
    return app


app = create_app()
