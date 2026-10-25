"""
Integration tests against a real SQL Server (marker: integration).
Run:  uv run pytest -m integration --no-cov     (needs DB_WRITER_URL in env or .env)
Read-only: these tests only SELECT.
"""

import pytest

from app.core.config import get_settings


pytestmark = pytest.mark.integration


@pytest.fixture
def require_db():
    if get_settings().DB_WRITER_URL is None:
        pytest.skip("DB_WRITER_URL not configured")


async def test_probe_real_database(require_db):
    from app.core.database import dispose_engines, get_db_session
    from app.services.health_service import probe_database

    try:
        async with get_db_session(use_reader=True) as session:
            st = await probe_database(session)
        assert st.database_name
        assert int(st.major_version) >= 13  # Change Tracking + JSON functions need 2016+
    finally:
        await dispose_engines()
