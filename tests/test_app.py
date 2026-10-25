from fastapi import APIRouter
from pydantic import BaseModel

from app.core.exceptions import ConflictError, TokenExpiredError


def test_unknown_route_uses_error_envelope(client):
    r = client.get("/no-such-route")
    assert r.status_code == 404
    assert r.json() == {"errorCode": "NOT_FOUND", "message": "Not Found"}


def test_security_and_request_headers(client):
    r = client.get("/health", headers={"X-Request-Id": "abc12345-req"})
    assert r.headers["x-request-id"] == "abc12345-req"
    assert int(r.headers["x-duration-ms"]) >= 0
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["content-security-policy"].startswith("default-src 'none'")
    assert r.headers["x-service-version"]


def test_unsafe_request_id_is_replaced(client):
    r = client.get("/health", headers={"X-Request-Id": "bad id\nwith newline"})
    assert r.headers["x-request-id"] != "bad id\nwith newline"
    assert len(r.headers["x-request-id"]) == 36


def _app_with_test_routes(app):
    router = APIRouter()

    class Body(BaseModel):
        count: int

    @router.post("/_t/validate")
    async def validate(body: Body):
        return body

    @router.get("/_t/conflict")
    async def conflict():
        raise ConflictError("User name already exists")

    @router.get("/_t/expired")
    async def expired():
        raise TokenExpiredError

    @router.get("/_t/boom")
    async def boom():
        raise RuntimeError("internal detail that must not leak")

    app.include_router(router)
    return app


def test_error_envelopes(app):
    from fastapi.testclient import TestClient

    c = TestClient(_app_with_test_routes(app), raise_server_exceptions=False)

    r = c.post("/_t/validate", json={"count": "x"})
    assert r.status_code == 422
    body = r.json()
    assert body["errorCode"] == "VALIDATION_ERROR"
    assert body["errors"][0]["loc"] == ["body", "count"]

    r = c.get("/_t/conflict")
    assert r.status_code == 409
    assert r.json() == {"errorCode": "CONFLICT", "message": "User name already exists"}

    r = c.get("/_t/expired")
    assert r.status_code == 401
    assert r.headers["x-token-expired"] == "true"

    r = c.get("/_t/boom")
    assert r.status_code == 500
    assert r.json() == {"errorCode": "INTERNAL_ERROR", "message": "An internal error occurred"}
    assert "internal detail" not in r.text


def test_docs_disabled_in_prod(monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("DB_WRITER_URL", "mssql+aioodbc://u:p@h:1433/db?driver=x")
    monkeypatch.setenv("JWT_PRIVATE_KEY_PEM", _test_pem())
    monkeypatch.setenv("OTP_SIGNING_KEY", "k" * 32)
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as c:
        assert c.get("/docs").status_code == 404
        assert c.get("/openapi.json").status_code == 404
        assert "strict-transport-security" in c.get("/health").headers


def _test_pem() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
