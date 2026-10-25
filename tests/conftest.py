"""
Test setup. Unit tests never touch a real database: the DB session dependency is
overridden with a fake. Integration tests (marker `integration`) need DB_WRITER_URL, are deselected by default
and refuse to run unless the server is approved and the database is sav_uat
(tests/integration/conftest.py).
"""

from collections.abc import Iterator
import os

import pytest


# Must be set before app modules read settings.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("LOG_JSON", "false")


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    from app.core.config import get_settings
    from app.core.security import get_auth_runtime

    get_settings.cache_clear()
    get_auth_runtime.cache_clear()
    yield
    get_settings.cache_clear()
    get_auth_runtime.cache_clear()


@pytest.fixture
def app():
    from app.main import create_app

    return create_app()


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c
