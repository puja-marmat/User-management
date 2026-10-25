from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
import multiprocessing
from pathlib import Path

import pytest

from app.services.masterdb_csv_store import (
    COLUMNS,
    CsvRoutingStore,
    RoutingRecord,
    RoutingStoreConstraintError,
    RoutingStoreError,
    RoutingStoreFormatError,
)
from app.services.masterdb_routing import first_containing


T0 = datetime(2026, 10, 23, 18, 30, 15, 123456)


def rec(name: str, status: int = 1, **kw) -> RoutingRecord:
    base = {
        "id": 0,
        "user_name": name,
        "base_url": "https://api.example.test",
        "payment_url": "https://pay.example.test",
        "created_at": T0,
        "updated_at": T0,
        "created_by_user_id": 7,
        "status_id": status,
    }
    base.update(kw)
    return RoutingRecord(**base)


def add(store: CsvRoutingStore, name: str, **kw):
    return store.create_if_absent(
        lambda rows: first_containing(rows, name), lambda i: rec(name, **kw)
    )


def test_missing_file_reads_empty_and_first_write_creates_it(tmp_path):
    store = CsvRoutingStore(tmp_path / "sub" / "routing.csv")
    assert store.read_all() == []
    assert not store.path.exists()
    created = add(store, "1001")
    assert created is not None and created.id == 1
    raw = store.path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM for Excel
    lines = raw.decode("utf-8-sig").split("\r\n")
    assert lines[0] == ",".join(COLUMNS)
    assert lines[1].startswith("1,1001,https://api.example.test,")
    assert "2026-10-23 18:30:15.123456" in lines[1]


def test_initialize_creates_header_once_and_never_overwrites(tmp_path):
    store = CsvRoutingStore(tmp_path / "routing.csv")
    assert store.initialize() is True
    add(store, "1001")
    assert store.initialize() is False
    assert len(store.read_all()) == 1


def test_round_trip_preserves_values_and_nulls(tmp_path):
    store = CsvRoutingStore(tmp_path / "r.csv")
    add(store, "Mätér-Ø 1", base_url=None, payment_url=None, created_by_user_id=None, status_id=0)
    (row,) = CsvRoutingStore(store.path).read_all()
    assert row == rec(
        "Mätér-Ø 1", id=1, base_url=None, payment_url=None, created_by_user_id=None, status_id=0
    )


def test_ids_are_identity_like(tmp_path):
    store = CsvRoutingStore(tmp_path / "r.csv")
    ids = [add(store, n).id for n in ("a1", "b2", "c3")]
    assert ids == [1, 2, 3]


def test_existing_match_skips_create(tmp_path):
    store = CsvRoutingStore(tmp_path / "r.csv")
    add(store, "1001234")
    assert add(store, "1234") is None  # substring of an existing name (legacy Contains)
    assert len(store.read_all()) == 1


def test_unique_username_is_enforced_case_insensitively(tmp_path):
    store = CsvRoutingStore(tmp_path / "r.csv")
    add(store, "Admin")
    with pytest.raises(RoutingStoreConstraintError):
        store.create_if_absent(lambda rows: None, lambda i: rec("ADMIN"))


@pytest.mark.parametrize(
    ("record", "msg"),
    [
        (rec(""), "required"),
        (rec("x" * 101), "100"),
        (rec("u1", base_url="h" * 501), "500"),
    ],
)
def test_masterdb_constraints(tmp_path, record, msg):
    store = CsvRoutingStore(tmp_path / "r.csv")
    with pytest.raises(RoutingStoreConstraintError, match=msg):
        store.create_if_absent(lambda rows: None, lambda i: record)
    assert not store.path.exists()


def test_update_changes_only_the_found_row(tmp_path):
    store = CsvRoutingStore(tmp_path / "r.csv")
    add(store, "1001")
    add(store, "2002")
    updated = store.update_found(
        lambda rows: first_containing(rows, "2002"), lambda r: replace(r, status_id=9)
    )
    assert updated is not None and updated.id == 2 and updated.status_id == 9
    rows = store.read_all()
    assert [r.status_id for r in rows] == [1, 9]


def test_update_without_match_writes_nothing(tmp_path):
    store = CsvRoutingStore(tmp_path / "r.csv")
    add(store, "1001")
    before = store.path.read_bytes()
    assert store.update_found(lambda rows: None, lambda r: r) is None
    assert store.path.read_bytes() == before


@pytest.mark.parametrize(
    "content",
    [
        "Id,UserName\r\n1,a\r\n",  # wrong header
        ",".join(COLUMNS) + "\r\nx,a,,,,,,1\r\n",  # Id not int
        ",".join(COLUMNS) + "\r\n1,,,,,,,1\r\n",  # UserName missing
        ",".join(COLUMNS) + "\r\n1,a,,,,,,1\r\n1,b,,,,,,1\r\n",  # duplicate Id
        ",".join(COLUMNS) + "\r\n1,a,,,,,,1\r\n2,A,,,,,,1\r\n",  # duplicate UserName
        ",".join(COLUMNS) + "\r\n1,a,,,notadate,,,1\r\n",  # bad datetime
        ",".join(COLUMNS) + "\r\n1,a,,,,,\r\n",  # missing column
    ],
)
def test_malformed_file_is_reported_and_never_overwritten(tmp_path, content):
    path = tmp_path / "r.csv"
    path.write_text(content, encoding="utf-8-sig", newline="")
    before = path.read_bytes()
    store = CsvRoutingStore(path)
    with pytest.raises(RoutingStoreFormatError):
        add(store, "new-user")
    with pytest.raises(RoutingStoreFormatError):
        store.initialize()
    assert path.read_bytes() == before


def test_header_only_and_blank_lines_are_accepted(tmp_path):
    path = tmp_path / "r.csv"
    path.write_text(",".join(COLUMNS) + "\r\n\r\n", encoding="utf-8-sig", newline="")
    assert CsvRoutingStore(path).read_all() == []


def test_write_failure_keeps_old_file_and_leaves_no_temp(tmp_path, monkeypatch):
    store = CsvRoutingStore(tmp_path / "r.csv")
    monkeypatch.setattr(CsvRoutingStore, "REPLACE_RETRY_DELAY", 0)
    add(store, "1001")
    before = store.path.read_bytes()

    def fail(self, target):
        raise PermissionError("file in use")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(RoutingStoreError):
        add(store, "2002")
    assert store.path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_lock_timeout_is_a_store_error(tmp_path):
    from filelock import FileLock

    store = CsvRoutingStore(tmp_path / "r.csv", lock_timeout_seconds=0.2)
    other = FileLock(str(store.path) + ".lock")
    # filelock is re-entrant per thread; take it from another thread instead
    with other, ThreadPoolExecutor(1) as pool, pytest.raises(RoutingStoreError, match="locked"):
        pool.submit(store.read_all).result()


def test_concurrent_threads_lose_no_rows_and_create_duplicates_once(tmp_path):
    store = CsvRoutingStore(tmp_path / "r.csv")
    names = [f"u{i:04d}" for i in range(40)]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda n: add(CsvRoutingStore(store.path), n), names))
        results = list(pool.map(lambda _: add(CsvRoutingStore(store.path), "same-name"), range(10)))
    rows = store.read_all()
    assert len(rows) == 41
    assert sorted(r.id for r in rows) == list(range(1, 42))
    assert sum(r is not None for r in results) == 1


def _proc_add(path: str, name: str) -> None:
    add(CsvRoutingStore(Path(path)), name)


def test_concurrent_processes_lose_no_rows(tmp_path):
    path = tmp_path / "r.csv"
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_proc_add, args=(str(path), f"p{i}")) for i in range(6)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    rows = CsvRoutingStore(path).read_all()
    assert sorted(r.user_name for r in rows) == [f"p{i}" for i in range(6)]


def test_transient_windows_lock_on_replace_is_retried(tmp_path, monkeypatch):
    import structlog

    store = CsvRoutingStore(tmp_path / "r.csv")
    add(store, "1001")
    monkeypatch.setattr(CsvRoutingStore, "REPLACE_RETRY_DELAY", 0)
    real_replace = Path.replace
    calls = {"n": 0}

    def flaky(self, target):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError("sharing violation (simulated anti-virus scan)")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky)
    with structlog.testing.capture_logs() as logs:
        assert add(store, "2002") is not None
    assert [e["attempt"] for e in logs if e["event"] == "masterdb_csv_replace_retry"] == [1, 2]
    assert [r.user_name for r in store.read_all()] == ["1001", "2002"]
    assert not list(tmp_path.glob("*.tmp"))
