"""
The integration-test safety guard and the unit-only default (no database needed).

All hosts below are synthetic (`*.example.test`, documentation IP ranges). The real UAT host
and its fingerprint are never in the repository.
"""

from pathlib import Path
import re
import tomllib

import pytest

from tests.integration import conftest
from tests.integration.target_guard import (
    APPROVED_SERVER_ENV,
    EXPECTED_DATABASE,
    WrongDatabaseError,
    WrongServerError,
    approved_fingerprints,
    check_database_names,
    check_server_targets,
    normalize_server,
    server_fingerprint,
)


HOST = "uat-db.example.test"
FP = server_fingerprint(HOST, 1433)
SECRET_USER = "guard_user_x"
SECRET_PASSWORD = "Guard-Pass-9!"


def _url(host: str, port: str = "", user: str = SECRET_USER, db: str = "sav_uat") -> str:
    hostport = f"{host}:{port}" if port else host
    return f"mssql+aioodbc://{user}:{SECRET_PASSWORD}@{hostport}/{db}?driver=ODBC+Driver+18"


ENV_OK = {APPROVED_SERVER_ENV: FP}


# ── database name ───────────────────────────────────────────────────────────


def test_expected_database_is_sav_uat():
    assert EXPECTED_DATABASE == "sav_uat"


@pytest.mark.parametrize(
    "names",
    [{"writer": "sav_uat", "reader": "sav_uat"}, {"writer": "SAV_UAT", "reader": "Sav_Uat"}],
)
def test_sav_uat_is_accepted(names):
    check_database_names(names)


@pytest.mark.parametrize(
    "names",
    [
        {"writer": "CrystalPower", "reader": "CrystalPower"},
        {"writer": "sav_uat", "reader": "CystalPowerMasterdb"},
        {"writer": "master", "reader": "sav_uat"},
        {"writer": None, "reader": "sav_uat"},
        {"writer": "sav_uat_copy", "reader": "sav_uat"},
        {"writer": "", "reader": ""},
    ],
)
def test_any_other_database_is_refused(names):
    with pytest.raises(WrongDatabaseError, match="must be 'sav_uat'"):
        check_database_names(names)


# ── server normalisation ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("host", "port", "expected"),
    [
        ("UAT-DB.Example.TEST", None, "uat-db.example.test:1433"),
        ("uat-db.example.test.", None, "uat-db.example.test:1433"),  # FQDN trailing dot
        ("  uat-db.example.test ", "", "uat-db.example.test:1433"),
        ("uat-db.example.test", 14330, "uat-db.example.test:14330"),
        ("uat-db.example.test", "1433", "uat-db.example.test:1433"),
        ("uat-db.example.test,1433", None, "uat-db.example.test:1433"),  # SQL Server form
        ("uat-db.example.test,14330", None, "uat-db.example.test:14330"),
        ("UAT-DB%5CInst01", None, "uat-db\\inst01:1433"),  # named instance, URL-encoded
        ("uat-db\\INST01", None, "uat-db\\inst01:1433"),
        ("192.0.2.10", None, "192.0.2.10:1433"),
        ("[2001:db8::10]", 1433, "[2001:db8::10]:1433"),
    ],
)
def test_normalize_server(host, port, expected):
    assert normalize_server(host, port) == expected


@pytest.mark.parametrize(
    ("host", "port"),
    [
        (None, None),
        ("", None),
        ("bad host", None),
        ("user@host.example.test", None),
        ("host.example.test", "abc"),
        ("host.example.test", 0),
        ("host.example.test", 70000),
        ("host.example.test,1433", 14330),  # conflicting ports
        ("host.example.test\\bad instance", None),
    ],
)
def test_malformed_servers_are_rejected(host, port):
    with pytest.raises(ValueError):
        normalize_server(host, port)


def test_fingerprint_is_case_and_default_port_insensitive_only():
    assert server_fingerprint("UAT-DB.EXAMPLE.TEST", None) == FP
    assert server_fingerprint("uat-db.example.test.", "1433") == FP
    assert server_fingerprint("uat-db.example.test,1433", None) == FP
    others = {
        server_fingerprint("alias-of-uat.example.test", None),  # DNS alias: not resolved
        server_fingerprint("192.0.2.10", None),  # IP of the same host: different identity
        server_fingerprint("uat-db.example.test", 14330),  # non-default port
        server_fingerprint("uat-db.example.test\\inst01", None),  # named instance
    }
    assert FP not in others and len(others) == 4
    assert re.fullmatch(r"[0-9a-f]{64}", FP)


# ── approved value (fail closed) ────────────────────────────────────────────


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_approval_fails_closed(value):
    env = {} if value is None else {APPROVED_SERVER_ENV: value}
    with pytest.raises(WrongServerError, match="is not set"):
        approved_fingerprints(env)


@pytest.mark.parametrize(
    "value",
    ["abc", FP[:-1], FP + "0", "g" * 64, f"{FP},", f"{FP},not-a-hash", HOST],
)
def test_malformed_approval_fails_closed(value):
    with pytest.raises(WrongServerError, match="SHA-256"):
        approved_fingerprints({APPROVED_SERVER_ENV: value})


def test_several_approved_values_and_upper_case_hex_are_accepted():
    other = server_fingerprint("alias-of-uat.example.test", None)
    assert approved_fingerprints({APPROVED_SERVER_ENV: f" {FP.upper()} , {other} "}) == {
        FP,
        other,
    }


# ── server check on the configured URLs ─────────────────────────────────────


def test_approved_writer_and_reader_pass():
    check_server_targets({"writer": _url(HOST), "reader": _url("UAT-DB.example.test.")}, ENV_OK)


@pytest.mark.parametrize(
    ("reader_url", "reason"),
    [
        (_url("alias-of-uat.example.test"), "not the approved"),
        (_url("192.0.2.10"), "not the approved"),
        (_url(HOST, port="14330"), "not the approved"),
        (_url("uat-db.example.test%5Cinst01"), "not the approved"),
        (_url("prod-db.example.test"), "not the approved"),
        ("mssql+aioodbc:///?odbc_connect=Server%3Dx", "cannot be determined"),  # no host
        ("not a url", "cannot be determined"),
    ],
)
def test_reader_on_another_server_is_refused(reader_url, reason):
    with pytest.raises(WrongServerError, match=reason) as exc:
        check_server_targets({"writer": _url(HOST), "reader": reader_url}, ENV_OK)
    assert "reader:" in str(exc.value) and "writer:" not in str(exc.value)


def test_an_alias_passes_only_when_it_was_approved_too():
    alias = "alias-of-uat.example.test"
    urls = {"writer": _url(HOST), "reader": _url(alias)}
    with pytest.raises(WrongServerError):
        check_server_targets(urls, ENV_OK)
    env = {APPROVED_SERVER_ENV: f"{FP},{server_fingerprint(alias, None)}"}
    check_server_targets(urls, env)


def test_expected_value_is_never_taken_from_the_url():
    # Passing the URL's own fingerprint is only possible through the approval variable.
    with pytest.raises(WrongServerError, match="is not set"):
        check_server_targets({"writer": _url(HOST)}, {})


def test_refusal_messages_hide_hosts_addresses_users_passwords_and_urls():
    urls = {"writer": _url("prod-db.example.test", "14330"), "reader": _url("192.0.2.77")}
    with pytest.raises(WrongServerError) as exc:
        check_server_targets(urls, ENV_OK)
    message = str(exc.value)
    for leaked in (
        "prod-db",
        "example.test",
        "192.0.2",
        "14330",
        SECRET_USER,
        SECRET_PASSWORD,
        "mssql",
        "://",
        FP,
    ):
        assert leaked not in message


# ── conftest wiring ─────────────────────────────────────────────────────────


@pytest.fixture
def db_url(monkeypatch):
    monkeypatch.setenv("DB_WRITER_URL", _url(HOST))
    monkeypatch.delenv("DB_READER_URL", raising=False)


def _names(writer="sav_uat", reader="sav_uat"):
    async def fake():
        return {"writer": writer, "reader": reader}

    return fake


def test_guard_passes_for_approved_server_and_sav_uat(monkeypatch, db_url):
    monkeypatch.setenv(APPROVED_SERVER_ENV, FP)
    monkeypatch.setattr(conftest, "read_database_names", _names())
    conftest.enforce_sav_uat()


@pytest.mark.parametrize("approval", [None, "", "not-a-hash"])
def test_guard_fails_closed_without_valid_approval_and_never_connects(
    monkeypatch, db_url, approval
):
    if approval is None:
        monkeypatch.delenv(APPROVED_SERVER_ENV, raising=False)
    else:
        monkeypatch.setenv(APPROVED_SERVER_ENV, approval)

    async def must_not_connect():  # pragma: no cover - would fail the test
        raise AssertionError("connected before the server check passed")

    monkeypatch.setattr(conftest, "read_database_names", must_not_connect)
    with pytest.raises(pytest.exit.Exception) as exc:
        conftest.enforce_sav_uat()
    assert exc.value.returncode == 3


def test_guard_checks_the_reader_url_before_connecting(monkeypatch, db_url):
    monkeypatch.setenv(APPROVED_SERVER_ENV, FP)
    monkeypatch.setenv("DB_READER_URL", _url("replica.example.test"))

    async def must_not_connect():  # pragma: no cover - would fail the test
        raise AssertionError("connected before the server check passed")

    monkeypatch.setattr(conftest, "read_database_names", must_not_connect)
    with pytest.raises(pytest.exit.Exception) as exc:
        conftest.enforce_sav_uat()
    assert "reader: server is not the approved" in str(exc.value)
    assert "replica" not in str(exc.value)


def test_guard_stops_on_a_wrong_database_name(monkeypatch, db_url):
    monkeypatch.setenv(APPROVED_SERVER_ENV, FP)
    monkeypatch.setattr(conftest, "read_database_names", _names("CrystalPower", "CrystalPower"))
    with pytest.raises(pytest.exit.Exception) as exc:
        conftest.enforce_sav_uat()
    assert exc.value.returncode == 3
    assert "must be 'sav_uat'" in str(exc.value)


def test_guard_suppresses_driver_error_details(monkeypatch, db_url):
    monkeypatch.setenv(APPROVED_SERVER_ENV, FP)

    async def failing():
        raise RuntimeError(f"Login failed for user '{SECRET_USER}' on server {HOST}")

    monkeypatch.setattr(conftest, "read_database_names", failing)
    with pytest.raises(pytest.exit.Exception) as exc:
        conftest.enforce_sav_uat()
    message = str(exc.value)
    assert "RuntimeError" in message and SECRET_USER not in message and HOST not in message


def test_guard_ignores_an_approval_written_only_in_dotenv(monkeypatch, tmp_path, db_url):
    (tmp_path / ".env").write_text(f"{APPROVED_SERVER_ENV}={FP}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(APPROVED_SERVER_ENV, raising=False)
    monkeypatch.setattr(conftest, "read_database_names", _names())
    with pytest.raises(pytest.exit.Exception, match="is not set"):
        conftest.enforce_sav_uat()


def test_guard_does_nothing_without_a_database_url(monkeypatch):
    async def must_not_be_called():  # pragma: no cover - would fail the test
        raise AssertionError("connected without DB_WRITER_URL")

    monkeypatch.setenv("DB_WRITER_URL", "")
    monkeypatch.setattr(conftest, "read_database_names", must_not_be_called)
    conftest.enforce_sav_uat()


def test_guard_is_a_session_fixture():
    source = (Path(__file__).parent / "integration" / "conftest.py").read_text("utf-8")
    assert '@pytest.fixture(scope="session", autouse=True)' in source
    assert "enforce_sav_uat()" in source


def test_no_server_fingerprint_is_hardcoded_in_the_repository():
    root = Path(__file__).parents[1]
    hex64 = re.compile(r"\b[0-9a-fA-F]{64}\b")
    files = [
        *root.glob("app/**/*.py"),
        *root.glob("tests/**/*.py"),
        *root.glob("docs/*.md"),
        *root.glob("*.md"),
        root / ".env.example",
    ]
    offenders = [str(f) for f in files if f.is_file() and hex64.search(f.read_text("utf-8"))]
    assert offenders == []


# ── default command is unit-only ────────────────────────────────────────────


def test_default_pytest_run_deselects_integration_tests():
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text("utf-8"))
    addopts = pyproject["tool"]["pytest"]["ini_options"]["addopts"]
    assert '-m "not integration"' in addopts
    assert pyproject["tool"]["coverage"]["report"]["fail_under"] == 70
