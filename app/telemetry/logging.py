"""
Structured logging (structlog → JSON on stdout), as ems-mdp-backend.
Request id is bound per request by RequestContextMiddleware.

Never log credentials, tokens, password hashes, connection strings or personal data.
"""

import logging
import sys

import structlog

from app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer = (
        structlog.processors.JSONRenderer()
        if settings.LOG_JSON
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[
            *shared,
            structlog.processors.EventRenamer("message"),
            structlog.processors.dict_tracebacks,
            lambda _l, _m, ev: {"service": settings.APP_NAME, "env": settings.ENVIRONMENT, **ev},
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging (uvicorn, sqlalchemy, alembic) to stdout at the same level.
    logging.basicConfig(level=level, stream=sys.stdout, format="%(levelname)s %(name)s %(message)s")
    # SQL echo is controlled by DB_ECHO only; keep the engine logger quiet otherwise.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DB_ECHO else logging.WARNING
    )
