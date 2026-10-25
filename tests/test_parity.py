"""Parity harness (P1-M1): read-only queries, redaction, delta, compare — synthetic data."""

from datetime import datetime
import json
import uuid

import pytest
from sqlalchemy.dialects import mssql

from app.parity import __main__ as cli
from app.parity.compare import compare, delta
from app.parity.snapshot import (
    ParityError,
    Selection,
    build_table_query,
    key_fingerprint,
    redact_row,
    take_snapshot,
)
from app.parity.tables import PARITY_TABLES, TABLES_BY_NAME


KEY = b"unit-test-parity-key"


def sql(stmt) -> str:
    return str(stmt.compile(dialect=mssql.dialect(), compile_kwargs={"literal_binds": True}))


# ── queries are SELECT-only and scoped ──────────────────────────────────────
def test_all_queries_are_scoped_selects():
    for spec in PARITY_TABLES:
        stmt = build_table_query(spec, [5, 6], since_id=100)
        text = sql(stmt).upper()
        assert text.startswith("SELECT")
        words = set(text.replace(",", " ").split())
        assert not words & {
            "INSERT",
            "UPDATE",
            "DELETE",
            "MERGE",
            "DROP",
            "ALTER",
            "CREATE",
            "EXEC",
        }
        assert "IN (5, 6)" in text
        if spec.append_only:
            assert "> 100" in text


def test_baseline_snapshot_reads_no_history_from_append_only_tables():
    for spec in PARITY_TABLES:
        stmt = build_table_query(spec, [5], since_id=None)
        assert (stmt is None) == spec.append_only


def test_unscoped_mutable_tables_are_never_read():
    for spec in PARITY_TABLES:
        if not spec.append_only:
            assert build_table_query(spec, [], since_id=0) is None


def test_alert_queue_without_sites_reads_only_new_rows():
    spec = TABLES_BY_NAME["AlertQueues"]
    text = sql(build_table_query(spec, [], since_id=40))
    assert "> 40" in text and " IN " not in text


def test_selection_validation():
    with pytest.raises(ParityError):
        Selection().validate()
    with pytest.raises(ParityError):
        Selection(user_ids=(1, 2), subject_names=("a",)).validate()


# ── redaction ───────────────────────────────────────────────────────────────
def test_personal_fields_hashed_and_subject_names_substituted():
    spec = TABLES_BY_NAME["ApplicationUsers"]
    row = {
        "Id": 7,
        "UserName": "PT_legacy_01",
        "Email": "someone@example.test",
        "PhoneNumber": "9999900000",
        "StatusId": 1,
        "Guid": uuid.UUID(int=1),
        "CreatedDate": datetime(2026, 10, 23, 12, 0),
        "PasswordHash": "AQAAAA-synthetic",
    }
    out = redact_row(spec, row, KEY, ["pt_legacy_01"])
    text = json.dumps(out)
    for secret in ("someone@example.test", "9999900000", "AQAAAA-synthetic", "PT_legacy_01"):
        assert secret not in text
    assert out["StatusId"] == 1 and out["Id"] == 7
    assert out["Email"].startswith("h:")
    other = redact_row(spec, {**row, "UserName": "pt_new_01"}, KEY, ["pt_new_01"])
    assert other["UserName"] == out["UserName"]  # both became <SUBJECT1> before hashing


def test_hashes_depend_on_the_key():
    spec = TABLES_BY_NAME["ApplicationUsers"]
    a = redact_row(spec, {"Email": "x@example.test"}, KEY, [])
    b = redact_row(spec, {"Email": "x@example.test"}, b"other", [])
    assert a != b


# ── take_snapshot with a fake read-only session ──────────────────────────────
class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows, self._scalar = rows or [], scalar

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, data):
        self.data, self.statements, self.rolled_back = data, [], False

    async def execute(self, stmt):
        text = sql(stmt)
        self.statements.append(text)
        table = stmt.get_final_froms()[0].name
        rows = self.data.get(table, [])
        if len(stmt.selected_columns) == 1:
            return FakeResult(scalar=max((r["Id"] for r in rows), default=None))
        return FakeResult(rows=[r for r in rows if r["Id"] > 0])

    async def rollback(self):
        self.rolled_back = True


DATA = {
    "ApplicationUsers": [{"Id": 7, "UserName": "pt_1", "StatusId": 1, "Email": "a@example.test"}],
    "UserSites": [{"Id": 3, "ApplicationUserId": 7, "SiteId": 5}],
    "AlertQueues": [{"Id": 50, "SiteId": 5, "Message": "OTP 123456", "IsSent": False}],
}


async def test_take_snapshot_reads_only_and_rolls_back():
    session = FakeSession(DATA)
    snap = await take_snapshot(session, Selection(user_ids=(7,), site_ids=(5,)), KEY)
    assert session.rolled_back
    assert all(s.upper().startswith("SELECT") for s in session.statements)
    assert snap["keyFingerprint"] == key_fingerprint(KEY)
    assert snap["tables"]["ApplicationUsers"]["rows"]["7"]["StatusId"] == 1
    assert snap["tables"]["AlertQueues"]["rows"] == {}  # baseline: append-only not read
    assert snap["tables"]["AlertQueues"]["maxId"] == 50
    assert "OTP 123456" not in json.dumps(snap)


async def test_row_limit_protects_against_wide_selections():
    data = {"UserSites": [{"Id": i, "ApplicationUserId": 7, "SiteId": 5} for i in range(1, 6)]}
    with pytest.raises(ParityError, match="narrow"):
        await take_snapshot(FakeSession(data), Selection(user_ids=(7,)), KEY, row_limit=3)


async def test_baseline_with_other_key_is_rejected():
    before = await take_snapshot(FakeSession(DATA), Selection(user_ids=(7,)), KEY)
    with pytest.raises(ParityError, match="PARITY_HASH_KEY"):
        await take_snapshot(FakeSession(DATA), Selection(user_ids=(7,)), b"other", before)


# ── delta and compare ───────────────────────────────────────────────────────
def snap(tables, user_ids, fp=None):
    return {
        "kind": "u01-parity-snapshot",
        "version": 1,
        "keyFingerprint": fp or key_fingerprint(KEY),
        "selection": {"userIds": user_ids},
        "tables": {t: {"maxId": 0, "rows": r} for t, r in tables.items()},
    }


def side(uid: int, gid: uuid.UUID, status_after: int):
    before = snap({"ApplicationUsers": {}, "UserSites": {}}, [uid])
    after = snap(
        {
            "ApplicationUsers": {
                str(uid): {
                    "Id": uid,
                    "UserName": "h:SUBJ",
                    "StatusId": status_after,
                    "Guid": str(gid),
                }
            },
            "UserSites": {
                "1": {"Id": uid * 10, "ApplicationUserId": uid, "SiteId": 5, "Guid": str(gid)}
            },
        },
        [uid],
    )
    return delta(before, after)


def test_same_action_on_both_apps_is_equal_despite_ids_and_guids():
    a = side(101, uuid.uuid4(), 1)
    b = side(202, uuid.uuid4(), 1)
    assert compare(a, b)["equal"] is True


def test_difference_is_reported_without_raw_values():
    report = compare(side(101, uuid.uuid4(), 1), side(202, uuid.uuid4(), 0))
    assert report["equal"] is False
    diff = report["tables"]["ApplicationUsers"]["added"]
    assert diff["onlyInA"][0]["StatusId"] == 1 and diff["onlyInB"][0]["StatusId"] == 0
    assert "Id" not in diff["onlyInA"][0] and "Guid" not in diff["onlyInA"][0]  # volatile


def test_changed_rows_and_removed_rows():
    before = snap(
        {
            "ApplicationUsersInGroups": {
                "9": {"Id": 9, "ApplicationUserId": 1, "ApplicationRoleGroupId": 2}
            }
        },
        [1],
    )
    after = snap(
        {
            "ApplicationUsersInGroups": {
                "10": {"Id": 10, "ApplicationUserId": 1, "ApplicationRoleGroupId": 3}
            }
        },
        [1],
    )
    d = delta(before, after)["tables"]["ApplicationUsersInGroups"]
    assert len(d["added"]) == 1 and len(d["removed"]) == 1  # delete-then-insert, like legacy
    b2 = snap({"ApplicationUsers": {"1": {"Id": 1, "StatusId": 1}}}, [1])
    a2 = snap({"ApplicationUsers": {"1": {"Id": 1, "StatusId": 0}}}, [1])
    ch = delta(b2, a2)["tables"]["ApplicationUsers"]["changed"]
    assert ch[0]["changes"] == {"StatusId": [1, 0]}


def test_mismatched_keys_are_rejected():
    with pytest.raises(ParityError):
        delta(snap({}, [1]), snap({}, [1], fp="other"))


# ── CLI ─────────────────────────────────────────────────────────────────────
def test_cli_delta_and_compare(tmp_path):
    b, a = tmp_path / "b.json", tmp_path / "a.json"
    b.write_text(json.dumps(snap({"UserSites": {}}, [1])), encoding="utf-8")
    a.write_text(
        json.dumps(snap({"UserSites": {"5": {"Id": 5, "ApplicationUserId": 1, "SiteId": 3}}}, [1])),
        encoding="utf-8",
    )
    d = tmp_path / "d.json"
    assert cli.main(["delta", str(b), str(a), "--out", str(d)]) == 0
    assert cli.main(["compare", str(d), str(d), "--out", str(tmp_path / "r.json")]) == 0
    other = tmp_path / "o.json"
    other.write_text(
        json.dumps(delta(snap({"UserSites": {}}, [1]), snap({"UserSites": {}}, [1]))),
        encoding="utf-8",
    )
    assert cli.main(["compare", str(d), str(other)]) == 1


def test_cli_snapshot_requires_selection_and_key(monkeypatch, capsys):
    from app.core.config import get_settings

    assert cli.main(["snapshot"]) == 2
    assert "select at least one" in capsys.readouterr().err
    monkeypatch.setattr(get_settings(), "PARITY_HASH_KEY", None)
    assert cli.main(["snapshot", "--user-ids", "1"]) == 2
    assert "PARITY_HASH_KEY" in capsys.readouterr().err


def test_cli_rejects_bad_ids_and_missing_files(capsys):
    assert cli.main(["snapshot", "--user-ids", "1,x"]) == 2
    assert cli.main(["delta", "missing1.json", "missing2.json"]) == 2
