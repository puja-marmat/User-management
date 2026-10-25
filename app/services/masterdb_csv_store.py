"""
CSV store for MasterDb routing rows (U01 DEC-44, Phase 1).

Stands in for `CystalPowerMasterdb.dbo.ApplicationUsers` until MasterDb is connected.
The file has exactly the eight MasterDb columns [DB `CystalPowerMasterdb_script.sql`]:

    Id               int, IDENTITY(1,1), NOT NULL      → assigned here as max(Id) + 1
    UserName         nvarchar(100), NOT NULL, UNIQUE   → unique index IX_ApplicationUsers_UserName
    BaseUrl          nvarchar(500), NULL
    PaymentUrl       nvarchar(500), NULL
    CreatedAt        datetime2(7), NULL                → India local time, written by the app
    UpdatedAt        datetime2(7), NULL
    CreatedByUserId  int, NULL
    StatusId         int, NOT NULL

Format: UTF-8 with BOM (so Excel shows non-ASCII names correctly), comma-separated,
CRLF line ends, header row exactly as above, empty cell = NULL, datetimes as
`YYYY-MM-DD HH:MM:SS.ffffff`. An empty cell cannot tell NULL from an empty string;
both read back as NULL (MasterDb import later must treat them alike). Open it read-only in Excel while the API runs: Excel locks
the file on Windows and writes would then fail (they are logged, not fatal).

Safety:
- One writer at a time: an OS file lock (`<file>.lock`, via `filelock`) plus an in-process
  lock; lookup-and-insert / lookup-and-update run under the same lock (no lost updates).
- Atomic replace: the new content is written to a temp file in the same folder, flushed,
  fsync-ed and moved over the old file (`Path.replace`, atomic on the same volume).
- Windows: anti-virus, the search indexer or Excel can hold the target file for a moment,
  so the final replace is retried on PermissionError for up to ~2 s (`REPLACE_RETRIES` x
  `REPLACE_RETRY_DELAY`) before failing; each retry is logged (no row data).
- A file with an unexpected header or malformed rows is never overwritten; operations
  fail with `RoutingStoreFormatError` until a person fixes the file.
- No row contents are logged.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import csv
from dataclasses import dataclass, replace
from datetime import datetime
import io
import os
from pathlib import Path
import tempfile
import threading
import time

from filelock import FileLock, Timeout
import structlog


COLUMNS: tuple[str, ...] = (
    "Id",
    "UserName",
    "BaseUrl",
    "PaymentUrl",
    "CreatedAt",
    "UpdatedAt",
    "CreatedByUserId",
    "StatusId",
)
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
MAX_USERNAME = 100
MAX_URL = 500
ENCODING = "utf-8-sig"

log = structlog.get_logger(__name__)


class RoutingStoreError(Exception):
    """Any failure of the routing store (I/O, lock timeout, constraint)."""


class RoutingStoreFormatError(RoutingStoreError):
    """The CSV exists but does not have the expected header or row format."""


class RoutingStoreConstraintError(RoutingStoreError):
    """Write would break a MasterDb constraint (NOT NULL, length, unique UserName)."""


@dataclass(frozen=True)
class RoutingRecord:
    id: int
    user_name: str
    base_url: str | None
    payment_url: str | None
    created_at: datetime | None
    updated_at: datetime | None
    created_by_user_id: int | None
    status_id: int


def _fmt_dt(value: datetime | None) -> str:
    return "" if value is None else value.strftime(DATETIME_FORMAT)


def _parse_dt(value: str, line: int, column: str) -> datetime | None:
    if value == "":
        return None
    try:
        return datetime.strptime(value, DATETIME_FORMAT)
    except ValueError:
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise RoutingStoreFormatError(f"line {line}: {column} is not a datetime") from exc


def _parse_int(value: str, line: int, column: str, *, nullable: bool) -> int | None:
    if value == "":
        if nullable:
            return None
        raise RoutingStoreFormatError(f"line {line}: {column} is required")
    try:
        return int(value)
    except ValueError as exc:
        raise RoutingStoreFormatError(f"line {line}: {column} is not an integer") from exc


def _opt(value: str) -> str | None:
    return None if value == "" else value


class CsvRoutingStore:
    """Thread- and process-safe CSV table with MasterDb `ApplicationUsers` semantics."""

    REPLACE_RETRIES = 20
    REPLACE_RETRY_DELAY = 0.1  # seconds

    def __init__(self, path: Path, lock_timeout_seconds: float = 10.0) -> None:
        self.path = Path(path)
        self._file_lock = FileLock(str(self.path) + ".lock", timeout=lock_timeout_seconds)
        self._thread_lock = threading.RLock()

    # ── public operations (each runs under the lock) ─────────────────────────
    def read_all(self) -> list[RoutingRecord]:
        with self._locked():
            return self._load()

    def initialize(self) -> bool:
        """Create the file with only the header if it does not exist. Returns True if created."""
        with self._locked():
            if self.path.exists() and self.path.stat().st_size > 0:
                self._load()  # validate an existing file, never overwrite it
                return False
            self._save([])
            return True

    def create_if_absent(
        self,
        lookup: Callable[[list[RoutingRecord]], RoutingRecord | None],
        build: Callable[[int], RoutingRecord],
    ) -> RoutingRecord | None:
        """If `lookup(rows)` finds nothing, insert `build(new_id)`. Returns the new row or None."""
        with self._locked():
            rows = self._load()
            if lookup(rows) is not None:
                return None
            new_id = max((r.id for r in rows), default=0) + 1
            record = replace(build(new_id), id=new_id)
            self._check_constraints(record, rows)
            self._save([*rows, record])
            return record

    def update_found(
        self,
        lookup: Callable[[list[RoutingRecord]], RoutingRecord | None],
        change: Callable[[RoutingRecord], RoutingRecord],
    ) -> RoutingRecord | None:
        """If `lookup(rows)` finds a row, replace it with `change(row)`. Returns it or None."""
        with self._locked():
            rows = self._load()
            found = lookup(rows)
            if found is None:
                return None
            updated = replace(change(found), id=found.id)
            others = [r for r in rows if r.id != found.id]
            self._check_constraints(updated, others)
            self._save([updated if r.id == found.id else r for r in rows])
            return updated

    # ── internals ───────────────────────────────────────────────────────────
    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._thread_lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._file_lock.acquire()
            except Timeout as exc:
                raise RoutingStoreError("routing file is locked by another process") from exc
            except OSError as exc:
                raise RoutingStoreError("cannot create or lock the routing file") from exc
            try:
                yield
            finally:
                self._file_lock.release()

    def _load(self) -> list[RoutingRecord]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return []
        try:
            text = self.path.read_text(encoding=ENCODING)
        except (OSError, UnicodeDecodeError) as exc:
            raise RoutingStoreError("cannot read the routing file") from exc
        reader = csv.reader(io.StringIO(text, newline=""))
        try:
            header = next(reader)
        except StopIteration:
            return []
        if tuple(header) != COLUMNS:
            raise RoutingStoreFormatError(
                "unexpected header in routing file; expected: " + ",".join(COLUMNS)
            )
        rows: list[RoutingRecord] = []
        seen_ids: set[int] = set()
        seen_names: set[str] = set()
        for line, cells in enumerate(reader, start=2):
            if not cells or all(c == "" for c in cells):
                continue
            if len(cells) != len(COLUMNS):
                raise RoutingStoreFormatError(f"line {line}: expected {len(COLUMNS)} columns")
            rid = _parse_int(cells[0], line, "Id", nullable=False)
            status = _parse_int(cells[7], line, "StatusId", nullable=False)
            if cells[1] == "":
                raise RoutingStoreFormatError(f"line {line}: UserName is required")
            if rid in seen_ids:
                raise RoutingStoreFormatError(f"line {line}: duplicate Id")
            if cells[1].casefold() in seen_names:
                raise RoutingStoreFormatError(f"line {line}: duplicate UserName")
            seen_ids.add(rid)  # type: ignore[arg-type]
            seen_names.add(cells[1].casefold())
            rows.append(
                RoutingRecord(
                    id=rid,  # type: ignore[arg-type]
                    user_name=cells[1],
                    base_url=_opt(cells[2]),
                    payment_url=_opt(cells[3]),
                    created_at=_parse_dt(cells[4], line, "CreatedAt"),
                    updated_at=_parse_dt(cells[5], line, "UpdatedAt"),
                    created_by_user_id=_parse_int(cells[6], line, "CreatedByUserId", nullable=True),
                    status_id=status,  # type: ignore[arg-type]
                )
            )
        return rows

    @staticmethod
    def _check_constraints(record: RoutingRecord, others: list[RoutingRecord]) -> None:
        if not record.user_name:
            raise RoutingStoreConstraintError("UserName is required (NOT NULL)")
        if len(record.user_name) > MAX_USERNAME:
            raise RoutingStoreConstraintError("UserName longer than 100 characters")
        for url in (record.base_url, record.payment_url):
            if url is not None and len(url) > MAX_URL:
                raise RoutingStoreConstraintError("URL longer than 500 characters")
        name = record.user_name.casefold()
        if any(o.user_name.casefold() == name for o in others):
            raise RoutingStoreConstraintError("UserName already exists (unique index)")

    def _replace_with_retry(self, tmp: Path) -> None:
        for attempt in range(1, self.REPLACE_RETRIES + 1):
            try:
                tmp.replace(self.path)
            except PermissionError:
                if attempt == self.REPLACE_RETRIES:
                    raise
                log.warning("masterdb_csv_replace_retry", attempt=attempt)
                time.sleep(self.REPLACE_RETRY_DELAY)
            else:
                return

    def _save(self, rows: list[RoutingRecord]) -> None:
        buf = io.StringIO(newline="")
        writer = csv.writer(buf, lineterminator="\r\n")
        writer.writerow(COLUMNS)
        for r in sorted(rows, key=lambda x: x.id):
            writer.writerow(
                [
                    r.id,
                    r.user_name,
                    r.base_url or "",
                    r.payment_url or "",
                    _fmt_dt(r.created_at),
                    _fmt_dt(r.updated_at),
                    "" if r.created_by_user_id is None else r.created_by_user_id,
                    r.status_id,
                ]
            )
        data = buf.getvalue().encode(ENCODING)
        tmp_name = None
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent
            )
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            self._replace_with_retry(Path(tmp_name))
            tmp_name = None
        except OSError as exc:
            raise RoutingStoreError("cannot write the routing file") from exc
        finally:
            if tmp_name is not None:
                Path(tmp_name).unlink(missing_ok=True)
