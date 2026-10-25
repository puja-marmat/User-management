"""
Integration tests: refuse to run against anything but `sav_uat` on the approved server
(see `target_guard.py`).

The check runs once, before the first integration test of the session, and only when
integration tests are actually selected (`uv run pytest -m integration ...`). The default
`uv run pytest` deselects them (pyproject `addopts`), so it never opens a connection.
Order: server fingerprint of writer and reader URLs (no connection) → `SELECT DB_NAME()`
on both → tests. Any failure stops the whole run (exit code 3) with a message that holds no
host, address, user, password or URL.
"""

import asyncio
import os

import pytest

from app.core.config import get_settings
from tests.integration.target_guard import (
    WrongServerError,
    check_database_names,
    check_server_targets,
    read_database_names,
)


def enforce_sav_uat() -> None:
    """Stop the pytest run unless both connections target `sav_uat` on the approved server."""
    get_settings.cache_clear()
    try:
        settings = get_settings()
        if settings.DB_WRITER_URL is None:
            return  # each test skips itself ("DB_WRITER_URL not configured")
        urls = {"writer": settings.writer_url, "reader": settings.reader_url}
        check_server_targets(urls, os.environ)  # process environment only, never .env
        try:
            names = asyncio.run(read_database_names())
        except Exception as exc:  # driver messages can contain user/server names
            raise WrongServerError(
                "Integration tests refused: could not read DB_NAME() "
                f"({type(exc).__name__}; details suppressed)."
            ) from None
        check_database_names(names)
    except WrongServerError as exc:
        pytest.exit(str(exc), returncode=3)
    finally:
        get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def _require_sav_uat() -> None:
    enforce_sav_uat()
