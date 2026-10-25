"""
Read-only snapshots of the U01 tables for selected test users / role groups / sites.

Only SELECT statements are issued, inside a transaction that is always rolled back.
Personal columns are replaced by an HMAC (key `PARITY_HASH_KEY`), so snapshots can be
diffed and compared without exposing contact details, names, hashes or OTP text.
"""

import base64
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
import hashlib
import hmac
import re
from typing import Any
import uuid

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.legacy_time import india_now
from app.parity.tables import PARITY_TABLES, TableSpec


SNAPSHOT_KIND = "u01-parity-snapshot"
SNAPSHOT_VERSION = 1
DEFAULT_ROW_LIMIT = 500


class ParityError(Exception):
    """Invalid parity input (selection, key, files)."""


@dataclass(frozen=True)
class Selection:
    user_ids: tuple[int, ...] = ()
    role_group_ids: tuple[int, ...] = ()
    site_ids: tuple[int, ...] = ()
    subject_names: tuple[str, ...] = field(default=())  # same order as user_ids

    def ids_for(self, spec: TableSpec) -> tuple[int, ...]:
        return {
            "user": self.user_ids,
            "role_group": self.role_group_ids,
            "site": self.site_ids,
            "site_or_all": self.site_ids,
        }[spec.select_by]

    def validate(self) -> None:
        if not (self.user_ids or self.role_group_ids or self.site_ids):
            raise ParityError("select at least one --user-ids, --role-group-ids or --site-ids")
        if self.subject_names and len(self.subject_names) != len(self.user_ids):
            raise ParityError("--subject-names must match --user-ids one to one")


def key_fingerprint(key: bytes) -> str:
    return hmac.new(key, b"u01-parity-fingerprint", hashlib.sha256).hexdigest()[:12]


def _hash(key: bytes, value: str) -> str:
    digest = hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()
    return "h:" + base64.urlsafe_b64encode(digest[:12]).decode("ascii")


def _substitute_names(value: str, names: Sequence[str]) -> str:
    for i, name in enumerate(names, start=1):
        if name:
            value = re.sub(re.escape(name), f"<SUBJECT{i}>", value, flags=re.IGNORECASE)
    return value


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, uuid.UUID | Decimal):
        return str(value)
    if isinstance(value, bytes | bytearray):
        return "b:" + base64.b64encode(bytes(value)).decode("ascii")
    return str(value)


def redact_row(
    spec: TableSpec, row: Mapping[str, Any], key: bytes, subject_names: Sequence[str]
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for column, raw in row.items():
        value = _plain(raw)
        if isinstance(value, str) and subject_names:
            value = _substitute_names(value, subject_names)
        if column in spec.personal and value is not None:
            value = _hash(key, str(value))
        out[column] = value
    return out


def build_table_query(spec: TableSpec, ids: Iterable[int], since_id: int | None) -> Select | None:
    """SELECT for one table, or None when nothing should be read."""
    ids = tuple(ids)
    table = spec.table
    stmt = select(table)
    if spec.append_only:
        if since_id is None:
            return None  # baseline snapshot: only max(Id) is recorded
        stmt = stmt.where(table.c.Id > since_id)
        if ids:
            stmt = stmt.where(table.c[spec.filter_column].in_(ids))
        elif spec.select_by != "site_or_all":
            return None
    else:
        if not ids:
            return None
        stmt = stmt.where(table.c[spec.filter_column].in_(ids))
    return stmt.order_by(table.c.Id)


async def take_snapshot(
    session: AsyncSession,
    selection: Selection,
    key: bytes,
    baseline: Mapping[str, Any] | None = None,
    row_limit: int = DEFAULT_ROW_LIMIT,
) -> dict[str, Any]:
    """Read the selected rows (SELECT only, rolled back) and return a redacted snapshot."""
    selection.validate()
    if baseline is not None:
        check_compatible(baseline, key)
    tables: dict[str, Any] = {}
    try:
        for spec in PARITY_TABLES:
            max_id = (
                await session.execute(
                    select(spec.table.c.Id).order_by(spec.table.c.Id.desc()).limit(1)
                )
            ).scalar()
            since = None
            if baseline is not None:
                since = baseline["tables"].get(spec.name, {}).get("maxId") or 0
            stmt = build_table_query(spec, selection.ids_for(spec), since)
            rows: dict[str, Any] = {}
            if stmt is not None:
                result = (await session.execute(stmt.limit(row_limit + 1))).mappings().all()
                if len(result) > row_limit:
                    raise ParityError(
                        f"{spec.name}: more than {row_limit} rows; narrow the selection"
                    )
                for r in result:
                    rows[str(r["Id"])] = redact_row(spec, r, key, selection.subject_names)
            tables[spec.name] = {"maxId": max_id or 0, "rows": rows}
    finally:
        await session.rollback()
    return {
        "kind": SNAPSHOT_KIND,
        "version": SNAPSHOT_VERSION,
        "takenAtIst": india_now().isoformat(),
        "keyFingerprint": key_fingerprint(key),
        "selection": {
            "userIds": list(selection.user_ids),
            "roleGroupIds": list(selection.role_group_ids),
            "siteIds": list(selection.site_ids),
            "subjectNames": len(selection.subject_names),
        },
        "baselineTakenAtIst": baseline.get("takenAtIst") if baseline else None,
        "tables": tables,
    }


def check_compatible(doc: Mapping[str, Any], key: bytes) -> None:
    if doc.get("kind") != SNAPSHOT_KIND or doc.get("version") != SNAPSHOT_VERSION:
        raise ParityError("not a U01 parity snapshot (or a different version)")
    if doc.get("keyFingerprint") != key_fingerprint(key):
        raise ParityError("snapshot was hashed with a different PARITY_HASH_KEY")
