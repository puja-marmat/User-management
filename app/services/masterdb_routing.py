"""
MasterDb routing — legacy behaviour kept, storage swapped (U01 DEC-43, DEC-44).

Legacy source [Code `CrystalPower.Web/Controllers/UserManagement/UserController.cs`]:
- `AddOrUpdateUser` (create, :423) calls `CreateUserInMasterDb(user)` and (edit, :325)
  `UpdateUserInMasterDb(applicationUser)` only when appSetting `ClientName` == "SAV"
  (prod value "SAV" [Web.config]). Both run **after** the CrystalPower save.
- `CreateUserInMasterDb` (:959-1007) / `UpdateUserInMasterDb` (:1009-1056), in this order:
    1. `loggedInUser = GetById(current user id)`            → `RoutingContext.logged_in_user_id`
    2. `baseUrl = AppSettings["ApiBaseurl"]`                 → `MASTERDB_API_BASE_URL`
    3. `siteid = GetSiteIdOfLoginUser()` (admin's **current** site, not the new user's)
    4. `PayUSiteId` split on ',' ';', empty parts removed, `int.Parse(Trim())`
       (a missing key throws NullReferenceException, a non-number FormatException;
       both are caught by the method's catch → nothing written)
    5. `paymentUrl = "PayU"` if siteid in that list, else `AppSettings["PaymentUrl"]`
    6. `existing = _userRepository.GetByUserName(user.UserName).FirstOrDefault()`, where
       `GetByUserName` = `Users.Where(x => x.UserName.Contains(userName))`
       [Code `CrystalPower.Infrastructure/Repositories/UserRepository.cs:32-35`]
       → **substring** match (finding 101 F8, kept in Phase 1 per U01 P1.6)
    7. create: only if `existing == null`, insert
         UserName, BaseUrl = baseUrl ?? "Unknown", PaymentUrl = paymentUrl ?? user.Email,
         CreatedAt = UpdatedAt = India now, CreatedByUserId = loggedInUser?.Id,
         StatusId = user.StatusId
       update: only if `existing != null`, set BaseUrl, PaymentUrl (same rules), UpdatedAt,
         CreatedByUserId = loggedInUser?.Id (overwritten), StatusId; the lookup uses the
         user's **current (possibly new)** UserName (finding 101 F9, kept)
    8. any exception → `_log.Error(...)`; the user save is never failed by MasterDb.

Unverifiable details, decided here and documented:
- [Inferred] `Contains` is case-insensitive: SQL Server default collations are CI; the
  MasterDb collation is not in the schema script [To Confirm].
- [Inferred] `FirstOrDefault()` without `OrderBy` returns rows in an engine-chosen order;
  we take the lowest Id (clustered primary key order).
- CreatedAt and UpdatedAt use one timestamp (legacy reads the clock twice, microseconds apart).
- Errors are logged with the operation and error type only (legacy logged the message,
  which can contain the user name — not repeated here, CLAUDE.md personal-data rule).

This module only implements the behaviour. Wiring into Add/Edit User happens in P1-M4.
"""

from dataclasses import dataclass, replace
from enum import StrEnum
import re

import structlog

from app.core.config import Settings
from app.core.legacy_time import india_now
from app.services.masterdb_csv_store import CsvRoutingStore, RoutingRecord


log = structlog.get_logger(__name__)

UNKNOWN_BASE_URL = "Unknown"
PAYU_PAYMENT_URL = "PayU"
_INT_PARSE = re.compile(r"^[+-]?\d+$")  # what .NET int.Parse accepts (invariant digits)


class RoutingOutcome(StrEnum):
    CREATED = "created"
    ALREADY_EXISTS = "already_exists"  # create skipped: a (substring) match exists
    UPDATED = "updated"
    NOT_FOUND = "not_found"  # update skipped: no match
    SKIPPED_OFF = "skipped_off"  # MASTERDB_MODE=off
    FAILED = "failed"  # error logged; caller continues (legacy catch)


class MasterDbLiveNotAvailableError(RuntimeError):
    """MASTERDB_MODE=live chosen before an approved MasterDb integration exists."""


@dataclass(frozen=True)
class RoutingUser:
    """The CrystalPower user being created or edited (after the CrystalPower save)."""

    user_name: str | None
    email: str | None
    status_id: int


@dataclass(frozen=True)
class RoutingContext:
    """Who performs the action and on which site (legacy current-site cookie/claim)."""

    current_site_id: int | None
    logged_in_user_id: int | None


class _PayUSiteIdsError(Exception):
    pass


def parse_payu_site_ids(raw: str | None) -> list[int]:
    """Same result as legacy: missing setting → error; empty parts dropped; int.Parse(Trim())."""
    if raw is None:
        raise _PayUSiteIdsError("PayUSiteId setting missing")
    parts = [p for p in re.split(r"[,;]", raw) if p != ""]
    ids: list[int] = []
    for part in parts:
        value = part.strip()
        if not _INT_PARSE.match(value):
            raise _PayUSiteIdsError("PayUSiteId contains a non-integer value")
        ids.append(int(value))
    return ids


def first_containing(rows: list[RoutingRecord], user_name: str | None) -> RoutingRecord | None:
    """`Users.Where(x => x.UserName.Contains(userName)).FirstOrDefault()`."""
    needle = (user_name or "").casefold()
    for row in sorted(rows, key=lambda r: r.id):
        if needle in row.user_name.casefold():
            return row
    return None


class MasterDbRoutingService:
    def __init__(self, settings: Settings, store: CsvRoutingStore | None = None) -> None:
        self._settings = settings
        self.mode = settings.MASTERDB_MODE
        if self.mode == "live":
            raise MasterDbLiveNotAvailableError(
                "MASTERDB_MODE=live is not implemented in Phase 1; MasterDb is not connected"
            )
        self._store = (
            store
            if store is not None or self.mode != "file"
            else CsvRoutingStore(
                settings.MASTERDB_FILE_PATH, settings.MASTERDB_LOCK_TIMEOUT_SECONDS
            )
        )

    # ── legacy CreateUserInMasterDb ─────────────────────────────────────────
    def on_user_created(self, user: RoutingUser, ctx: RoutingContext) -> RoutingOutcome:
        if self.mode == "off":
            return RoutingOutcome.SKIPPED_OFF
        try:
            base_url, payment_url = self._urls(ctx)
            now = india_now()

            def build(new_id: int) -> RoutingRecord:
                return RoutingRecord(
                    id=new_id,
                    user_name=user.user_name or "",
                    base_url=base_url if base_url is not None else UNKNOWN_BASE_URL,
                    payment_url=payment_url if payment_url is not None else user.email,
                    created_at=now,
                    updated_at=now,
                    created_by_user_id=ctx.logged_in_user_id,
                    status_id=user.status_id,
                )

            created = self._require_store().create_if_absent(
                lambda rows: first_containing(rows, user.user_name), build
            )
            outcome = RoutingOutcome.CREATED if created else RoutingOutcome.ALREADY_EXISTS
        except Exception as exc:
            log.error("masterdb_routing_failed", operation="create", error_type=type(exc).__name__)
            return RoutingOutcome.FAILED
        log.info("masterdb_routing", operation="create", outcome=outcome.value, mode=self.mode)
        return outcome

    # ── legacy UpdateUserInMasterDb ─────────────────────────────────────────
    def on_user_updated(self, user: RoutingUser, ctx: RoutingContext) -> RoutingOutcome:
        if self.mode == "off":
            return RoutingOutcome.SKIPPED_OFF
        try:
            base_url, payment_url = self._urls(ctx)
            now = india_now()

            def change(row: RoutingRecord) -> RoutingRecord:
                return replace(
                    row,
                    base_url=base_url if base_url is not None else UNKNOWN_BASE_URL,
                    payment_url=payment_url if payment_url is not None else user.email,
                    updated_at=now,
                    created_by_user_id=ctx.logged_in_user_id,
                    status_id=user.status_id,
                )

            updated = self._require_store().update_found(
                lambda rows: first_containing(rows, user.user_name), change
            )
            outcome = RoutingOutcome.UPDATED if updated else RoutingOutcome.NOT_FOUND
        except Exception as exc:
            log.error("masterdb_routing_failed", operation="update", error_type=type(exc).__name__)
            return RoutingOutcome.FAILED
        log.info("masterdb_routing", operation="update", outcome=outcome.value, mode=self.mode)
        return outcome

    # ── helpers ─────────────────────────────────────────────────────────────
    def _urls(self, ctx: RoutingContext) -> tuple[str | None, str | None]:
        base_url = self._settings.MASTERDB_API_BASE_URL
        payu_sites = parse_payu_site_ids(self._settings.PAYU_SITE_IDS)
        if ctx.current_site_id is not None and ctx.current_site_id in payu_sites:
            return base_url, PAYU_PAYMENT_URL
        return base_url, self._settings.MASTERDB_PAYMENT_URL

    def _require_store(self) -> CsvRoutingStore:
        if self._store is None:  # pragma: no cover - guarded by mode checks
            raise RuntimeError("routing store not configured")
        return self._store
