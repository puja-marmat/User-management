"""
Delta (before → after on one application) and compare (delta of legacy vs delta of new).

Typical PT1 run (U01 plan P1.8), on `sav_uat`, test users only:
  1. snapshot before → action in legacy cp-web (UAT) → snapshot after → delta A
  2. same for the new app with an equivalent test user → delta B
  3. compare A B: ignores volatile columns (ids, guids, clocks, password hashes, OTP text),
     maps each side's subject user ids to <USER1..n> and their names to <SUBJECT1..n>.
"""

from collections import Counter
from collections.abc import Mapping
import json
from typing import Any

from app.parity.snapshot import ParityError
from app.parity.tables import TABLES_BY_NAME


def delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    if before.get("keyFingerprint") != after.get("keyFingerprint"):
        raise ParityError("before/after snapshots use different PARITY_HASH_KEY values")
    out: dict[str, Any] = {
        "kind": "u01-parity-delta",
        "keyFingerprint": after.get("keyFingerprint"),
        "subjectUserIds": after["selection"]["userIds"],
        "tables": {},
    }
    for name, after_t in after["tables"].items():
        before_rows = before["tables"].get(name, {}).get("rows", {})
        after_rows = after_t.get("rows", {})
        added = [after_rows[k] for k in after_rows if k not in before_rows]
        removed = [before_rows[k] for k in before_rows if k not in after_rows]
        changed = []
        for k in after_rows:
            if k in before_rows and after_rows[k] != before_rows[k]:
                b, a = before_rows[k], after_rows[k]
                changed.append(
                    {
                        "row": a,
                        "changes": {c: [b.get(c), a.get(c)] for c in a if b.get(c) != a.get(c)},
                    }
                )
        out["tables"][name] = {"added": added, "removed": removed, "changed": changed}
    return out


def _normalise(table: str, row: Mapping[str, Any], subjects: list[int]) -> dict[str, Any]:
    spec = TABLES_BY_NAME[table]
    out = {}
    for col, val in row.items():
        if col in spec.volatile:
            continue
        if col in spec.user_ref and isinstance(val, int) and val in subjects:
            val = f"<USER{subjects.index(val) + 1}>"
        out[col] = val
    return out


def _norm_changed(table: str, item: Mapping[str, Any], subjects: list[int]) -> dict[str, Any]:
    spec = TABLES_BY_NAME[table]
    changes = {c: v for c, v in item["changes"].items() if c not in spec.volatile}
    return {"row": _normalise(table, item["row"], subjects), "changes": sorted(changes)}


def _key(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def compare(delta_a: Mapping[str, Any], delta_b: Mapping[str, Any]) -> dict[str, Any]:
    if delta_a.get("keyFingerprint") != delta_b.get("keyFingerprint"):
        raise ParityError("deltas use different PARITY_HASH_KEY values")
    sa = list(delta_a.get("subjectUserIds", []))
    sb = list(delta_b.get("subjectUserIds", []))
    report: dict[str, Any] = {"kind": "u01-parity-compare", "equal": True, "tables": {}}
    for table in sorted(set(delta_a["tables"]) | set(delta_b["tables"])):
        ta = delta_a["tables"].get(table, {"added": [], "removed": [], "changed": []})
        tb = delta_b["tables"].get(table, {"added": [], "removed": [], "changed": []})
        result: dict[str, Any] = {}
        for part in ("added", "removed", "changed"):
            if part == "changed":
                ca = Counter(_key(_norm_changed(table, x, sa)) for x in ta[part])
                cb = Counter(_key(_norm_changed(table, x, sb)) for x in tb[part])
            else:
                ca = Counter(_key(_normalise(table, x, sa)) for x in ta[part])
                cb = Counter(_key(_normalise(table, x, sb)) for x in tb[part])
            only_a = list((ca - cb).elements())
            only_b = list((cb - ca).elements())
            if only_a or only_b:
                result[part] = {
                    "onlyInA": [json.loads(x) for x in only_a],
                    "onlyInB": [json.loads(x) for x in only_b],
                }
        if result:
            report["equal"] = False
            report["tables"][table] = result
    return report
