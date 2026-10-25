"""Legacy CreateUserInMasterDb / UpdateUserInMasterDb behaviour, CSV mode (U01 DEC-44)."""

from datetime import datetime

import pytest
import structlog

from app.core.config import Settings
from app.services import masterdb_routing as mr
from app.services.masterdb_csv_store import CsvRoutingStore, RoutingStoreError
from app.services.masterdb_routing import (
    MasterDbLiveNotAvailableError,
    MasterDbRoutingService,
    RoutingContext,
    RoutingOutcome,
    RoutingUser,
    first_containing,
    parse_payu_site_ids,
)


FIXED_NOW = datetime(2026, 10, 23, 23, 59, 59, 900000)


def settings(tmp_path, **kw) -> Settings:
    base = {
        "MASTERDB_MODE": "file",
        "MASTERDB_FILE_PATH": tmp_path / "routing.csv",
        "MASTERDB_API_BASE_URL": "https://api.example.test",
        "MASTERDB_PAYMENT_URL": "https://pay.example.test",
        "PAYU_SITE_IDS": "11, 12;13",
    }
    base.update(kw)
    return Settings(_env_file=None, **base)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(mr, "india_now", lambda: FIXED_NOW)


USER = RoutingUser(user_name="1000123", email="owner@example.test", status_id=1)
CTX = RoutingContext(current_site_id=5, logged_in_user_id=42)


def rows(tmp_path):
    return CsvRoutingStore(tmp_path / "routing.csv").read_all()


# ── create ───────────────────────────────────────────────────────────────────
def test_create_writes_one_row_like_legacy(tmp_path):
    svc = MasterDbRoutingService(settings(tmp_path))
    assert svc.on_user_created(USER, CTX) is RoutingOutcome.CREATED
    (r,) = rows(tmp_path)
    assert (r.id, r.user_name, r.base_url, r.payment_url) == (
        1,
        "1000123",
        "https://api.example.test",
        "https://pay.example.test",
    )
    assert r.created_at == r.updated_at == FIXED_NOW
    assert (r.created_by_user_id, r.status_id) == (42, 1)


def test_create_skipped_when_any_existing_name_contains_it(tmp_path):
    svc = MasterDbRoutingService(settings(tmp_path))
    svc.on_user_created(RoutingUser("A1000123B", None, 1), CTX)
    assert svc.on_user_created(USER, CTX) is RoutingOutcome.ALREADY_EXISTS
    assert len(rows(tmp_path)) == 1


def test_payu_site_gets_payu_payment_url(tmp_path):
    svc = MasterDbRoutingService(settings(tmp_path))
    svc.on_user_created(USER, RoutingContext(current_site_id=12, logged_in_user_id=42))
    assert rows(tmp_path)[0].payment_url == "PayU"


def test_no_current_site_is_not_payu(tmp_path):
    svc = MasterDbRoutingService(settings(tmp_path))
    svc.on_user_created(USER, RoutingContext(current_site_id=None, logged_in_user_id=None))
    (r,) = rows(tmp_path)
    assert r.payment_url == "https://pay.example.test" and r.created_by_user_id is None


def test_missing_settings_fall_back_like_legacy(tmp_path):
    svc = MasterDbRoutingService(
        settings(tmp_path, MASTERDB_API_BASE_URL=None, MASTERDB_PAYMENT_URL=None)
    )
    svc.on_user_created(USER, CTX)
    r = rows(tmp_path)[0]
    assert r.base_url == "Unknown"  # baseUrl ?? "Unknown"
    assert r.payment_url == "owner@example.test"  # paymentUrl ?? user.Email


def test_empty_payment_setting_is_not_null(tmp_path):
    svc = MasterDbRoutingService(settings(tmp_path, MASTERDB_PAYMENT_URL=""))
    svc.on_user_created(USER, CTX)
    # "" ?? email stays "" in legacy; CSV stores it as an empty cell
    assert rows(tmp_path)[0].payment_url is None


@pytest.mark.parametrize("raw", [None, "11,abc", "1.5"])
def test_bad_payu_setting_fails_softly_and_writes_nothing(tmp_path, raw, capsys):
    svc = MasterDbRoutingService(settings(tmp_path, PAYU_SITE_IDS=raw))
    assert svc.on_user_created(USER, CTX) is RoutingOutcome.FAILED
    assert not (tmp_path / "routing.csv").exists()


def test_empty_payu_setting_means_no_payu_sites(tmp_path):
    svc = MasterDbRoutingService(settings(tmp_path, PAYU_SITE_IDS=""))
    svc.on_user_created(USER, RoutingContext(current_site_id=12, logged_in_user_id=1))
    assert rows(tmp_path)[0].payment_url == "https://pay.example.test"


def test_parse_payu_site_ids_matches_net_split_and_parse():
    assert parse_payu_site_ids(" 1 ,;2;; +3 ,") == [1, 2, 3]
    assert parse_payu_site_ids("") == []
    for bad in ("1_0", "x", "1 2"):
        with pytest.raises(Exception, match="PayUSiteId"):
            parse_payu_site_ids(bad)


# ── update ───────────────────────────────────────────────────────────────────
def test_update_changes_legacy_fields_only(tmp_path):
    svc = MasterDbRoutingService(settings(tmp_path))
    svc.on_user_created(USER, CTX)
    created = rows(tmp_path)[0]
    svc2 = MasterDbRoutingService(
        settings(tmp_path, MASTERDB_API_BASE_URL="https://api2.example.test")
    )
    edited = RoutingUser("1000123", "new@example.test", status_id=0)
    assert svc2.on_user_updated(edited, RoutingContext(12, 77)) is RoutingOutcome.UPDATED
    (r,) = rows(tmp_path)
    assert r.id == created.id and r.user_name == created.user_name
    assert r.created_at == created.created_at
    assert (r.base_url, r.payment_url, r.created_by_user_id, r.status_id) == (
        "https://api2.example.test",
        "PayU",
        77,  # CreatedByUserId is overwritten by the editor, as legacy does
        0,
    )


def test_update_uses_the_new_username_and_skips_when_absent(tmp_path):
    svc = MasterDbRoutingService(settings(tmp_path))
    svc.on_user_created(USER, CTX)
    renamed = RoutingUser("9999999", USER.email, 1)
    assert svc.on_user_updated(renamed, CTX) is RoutingOutcome.NOT_FOUND
    assert rows(tmp_path)[0].user_name == "1000123"


def test_update_by_substring_hits_the_lowest_id(tmp_path):
    svc = MasterDbRoutingService(settings(tmp_path))
    with structlog.testing.capture_logs() as logs:
        outcomes = [
            svc.on_user_created(RoutingUser("X55Y", None, 1), CTX),
            svc.on_user_created(RoutingUser("Z55", None, 1), CTX),
            svc.on_user_updated(RoutingUser("55", None, 3), CTX),
        ]
    # On failure, show each outcome and the logged error type (diagnosis on Windows).
    detail = f"outcomes={[o.value for o in outcomes]} logs={logs}"
    assert outcomes == [RoutingOutcome.CREATED, RoutingOutcome.CREATED, RoutingOutcome.UPDATED], (
        detail
    )
    assert [r.status_id for r in rows(tmp_path)] == [3, 1], detail


def test_first_containing_is_case_insensitive_and_ordered():
    from tests.test_masterdb_csv_store import rec

    data = [rec("bcd", id=2), rec("ABC", id=1)]
    assert first_containing(data, "b").id == 1
    assert first_containing(data, "zz") is None
    assert first_containing(data, "").id == 1  # Contains("") matches everything


# ── modes and failures ───────────────────────────────────────────────────────
def test_off_mode_touches_nothing(tmp_path):
    svc = MasterDbRoutingService(settings(tmp_path, MASTERDB_MODE="off"))
    assert svc.on_user_created(USER, CTX) is RoutingOutcome.SKIPPED_OFF
    assert svc.on_user_updated(USER, CTX) is RoutingOutcome.SKIPPED_OFF
    assert not list(tmp_path.iterdir())


def test_live_mode_refuses_to_start(tmp_path):
    with pytest.raises(MasterDbLiveNotAvailableError):
        MasterDbRoutingService(settings(tmp_path, MASTERDB_MODE="live"))


def test_invalid_mode_rejected_by_settings(tmp_path):
    with pytest.raises(Exception, match="MASTERDB_MODE"):
        settings(tmp_path, MASTERDB_MODE="db")


def test_store_errors_are_logged_without_personal_data(tmp_path, monkeypatch):
    def broken(*a, **k):
        raise RoutingStoreError("cannot write the routing file")

    svc = MasterDbRoutingService(settings(tmp_path))
    monkeypatch.setattr(CsvRoutingStore, "create_if_absent", broken)
    monkeypatch.setattr(CsvRoutingStore, "update_found", broken)
    with structlog.testing.capture_logs() as logs:
        assert svc.on_user_created(USER, CTX) is RoutingOutcome.FAILED
        assert svc.on_user_updated(USER, CTX) is RoutingOutcome.FAILED
    events = [e for e in logs if e["event"] == "masterdb_routing_failed"]
    assert [e["operation"] for e in events] == ["create", "update"]
    text = repr(logs)
    assert "1000123" not in text and "example.test" not in text


def test_success_logs_have_no_personal_data(tmp_path):
    svc = MasterDbRoutingService(settings(tmp_path))
    with structlog.testing.capture_logs() as logs:
        svc.on_user_created(USER, CTX)
    assert logs and "1000123" not in repr(logs)
