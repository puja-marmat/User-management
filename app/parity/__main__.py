"""
U01 parity CLI (read-only against `sav_uat`).

  uv run python -m app.parity snapshot --user-ids 101 --subject-names pt_legacy_01 --out before.json
  uv run python -m app.parity snapshot --user-ids 101 --subject-names pt_legacy_01 \\
        --baseline before.json --out after.json
  uv run python -m app.parity delta before.json after.json --out legacy.delta.json
  uv run python -m app.parity compare legacy.delta.json new.delta.json --out report.json

Needs DB_WRITER_URL (or DB_READER_URL) for `snapshot` and PARITY_HASH_KEY for every command
that reads the database. Output files contain hashed personal fields only; keep them out
of Git anyway (`parity-out/` is ignored).
"""

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Any

from app.core.config import get_settings
from app.core.database import dispose_engines, get_db_session
from app.parity.compare import compare, delta
from app.parity.snapshot import ParityError, Selection, take_snapshot


def _ids(raw: str | None) -> tuple[int, ...]:
    if not raw:
        return ()
    try:
        return tuple(int(x) for x in raw.split(",") if x.strip())
    except ValueError as exc:
        raise ParityError("ids must be comma-separated integers") from exc


def _names(raw: str | None) -> tuple[str, ...]:
    return tuple(x.strip() for x in raw.split(",")) if raw else ()


def _key() -> bytes:
    key = get_settings().PARITY_HASH_KEY
    if key is None:
        raise ParityError("set PARITY_HASH_KEY (any long random local value) in .env")
    return key.get_secret_value().encode("utf-8")


def _load(path: str) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ParityError(f"cannot read {path}") from exc


def _write(doc: dict[str, Any], out: str | None) -> None:
    text = json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")


async def _snapshot(args: argparse.Namespace) -> dict[str, Any]:
    selection = Selection(
        user_ids=_ids(args.user_ids),
        role_group_ids=_ids(args.role_group_ids),
        site_ids=_ids(args.site_ids),
        subject_names=_names(args.subject_names),
    )
    selection.validate()
    key = _key()
    baseline = _load(args.baseline) if args.baseline else None
    try:
        async with get_db_session(use_reader=True) as session:
            return await take_snapshot(session, selection, key, baseline, args.row_limit)
    finally:
        await dispose_engines()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.parity",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot", help="read-only snapshot of the U01 tables")
    s.add_argument("--user-ids")
    s.add_argument("--role-group-ids")
    s.add_argument("--site-ids")
    s.add_argument("--subject-names", help="test user names, same order as --user-ids")
    s.add_argument("--baseline", help="'before' snapshot: capture rows added since it")
    s.add_argument("--row-limit", type=int, default=500)
    s.add_argument("--out")
    d = sub.add_parser("delta", help="before/after snapshots of one application")
    d.add_argument("before")
    d.add_argument("after")
    d.add_argument("--out")
    c = sub.add_parser("compare", help="delta A (legacy) vs delta B (new)")
    c.add_argument("delta_a")
    c.add_argument("delta_b")
    c.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "snapshot":
            _write(asyncio.run(_snapshot(args)), args.out)
            return 0
        if args.cmd == "delta":
            _write(delta(_load(args.before), _load(args.after)), args.out)
            return 0
        report = compare(_load(args.delta_a), _load(args.delta_b))
        _write(report, args.out)
        return 0 if report["equal"] else 1
    except ParityError as exc:
        sys.stderr.write(f"parity: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
