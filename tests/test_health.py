from types import SimpleNamespace

import pytest

from app.core.database import get_reader_db
from app.services import health_service


class _FakeResult:
    def __init__(self, row: dict) -> None:
        self._row = row

    def mappings(self):
        return SimpleNamespace(one=lambda: self._row)


class _FakeSession:
    def __init__(self, row: dict | None = None, exc: Exception | None = None) -> None:
        self.row, self.exc, self.calls = row, exc, []

    async def execute(self, stmt, params=None):
        self.calls.append(params)
        if self.exc:
            raise self.exc
        return _FakeResult(self.row)


ROW = {
    "database_name": "sav_uat",
    "product_version": "16.0.4135.4",
    "major_version": "16",
    "edition": "Developer Edition (64-bit)",
    "compatibility_level": 160,
    "iam_schema_exists": 0,
    "change_tracking_enabled": 0,
}


def _override(app, session):
    async def _dep():
        yield session

    app.dependency_overrides[get_reader_db] = _dep


def test_live(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "prime-mdm-backend"
    assert body["environment"] == "test"


def test_ready_reports_database_in_camel_case(app, client):
    session = _FakeSession(ROW)
    _override(app, session)
    r = client.get("/health/ready")
    assert r.status_code == 200
    db = r.json()["database"]
    assert db == {
        "name": "sav_uat",
        "productVersion": "16.0.4135.4",
        "majorVersion": "16",
        "edition": "Developer Edition (64-bit)",
        "compatibilityLevel": 160,
        "iamSchemaExists": False,
        "changeTrackingEnabled": False,
    }
    assert session.calls == [{"iam_schema": "iam"}]


def test_ready_hides_details_in_prod(app, client, monkeypatch):
    from app.core.config import get_settings

    _override(app, _FakeSession(ROW))
    monkeypatch.setattr(get_settings(), "ENVIRONMENT", "prod")
    r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}


def test_ready_db_down_returns_503_envelope_without_driver_text(app, client):
    secret_text = "Login failed for user 'someone' on server 'db-host'"
    _override(app, _FakeSession(exc=RuntimeError(secret_text)))
    r = client.get("/health/ready")
    assert r.status_code == 503
    assert r.json() == {"errorCode": "DB_UNAVAILABLE", "message": "Database not reachable"}
    assert "someone" not in r.text


async def test_probe_database_maps_row():
    st = await health_service.probe_database(_FakeSession({**ROW, "iam_schema_exists": 1}))
    assert st.iam_schema_exists is True
    assert st.major_version == "16"


async def test_probe_database_times_out(monkeypatch):
    import asyncio

    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "DB_HEALTH_TIMEOUT_SECONDS", 0.01)

    class _Slow(_FakeSession):
        async def execute(self, stmt, params=None):
            await asyncio.sleep(1)

    with pytest.raises(TimeoutError):
        await health_service.probe_database(_Slow())
