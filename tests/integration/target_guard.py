"""
Safety guard for integration tests (approved 2026-10-23).

Phase 1 may connect only to `sav_uat` on the approved server (U01 DEC-43). Before any
integration test runs, the session fixture in `tests/integration/conftest.py`:

1. **Server identity (no connection):** takes host and port of the writer and reader URLs,
   normalises them and compares their SHA-256 fingerprint with the approved fingerprint(s)
   in the environment variable `INTEGRATION_APPROVED_SERVER_SHA256`. That value is set
   independently by the user in the shell or Windows user environment — it is **never read
   from `.env`** and never derived from the URL being checked. Missing or malformed → refused
   (fail closed). DNS names are not resolved: an alias or an IP address has its own
   fingerprint and is refused unless it was approved too.
2. **Database name:** only then `SELECT DB_NAME()` on both connections; both must be `sav_uat`.

Messages never contain host names, IP addresses, ports, user names, passwords or URLs.

Compute the fingerprint of the host you were given for UAT (typed, not taken from `.env`):

    uv run python -m tests.integration.target_guard
"""

from collections.abc import Mapping
import hashlib
import re
from urllib.parse import unquote

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


EXPECTED_DATABASE = "sav_uat"
APPROVED_SERVER_ENV = "INTEGRATION_APPROVED_SERVER_SHA256"
DEFAULT_PORT = 1433
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_HOST_PART = re.compile(r"^[a-z0-9._:\[\]-]+$")  # DNS name, IPv4, [IPv6]
_INSTANCE = re.compile(r"^[a-z0-9_$#-]+$")


class WrongServerError(RuntimeError):
    """The configured server is not the approved one (or cannot be checked)."""


def normalize_server(host: str | None, port: int | str | None) -> str:
    """Canonical `host[\\instance]:port`, lower case; raises ValueError when malformed.

    * host: URL-decoded (`%5C` → `\\`), trimmed, lower-cased, trailing dot removed;
    * named instance kept (`host\\instance`); `host,port` accepted; port defaults to 1433;
    * no DNS lookup: aliases and IP addresses stay distinct identities.
    """
    raw = unquote(host or "").strip().lower()
    if "," in raw:  # SQL Server "host,port" form
        raw, _, port_text = raw.partition(",")
        if port not in (None, "") and str(port).strip() != port_text.strip():
            raise ValueError("conflicting ports")
        port = port_text.strip()
    server, _, instance = raw.partition("\\")
    server = server.rstrip(".")
    if not server or not _HOST_PART.match(server):
        raise ValueError("malformed host")
    if instance and not _INSTANCE.match(instance):
        raise ValueError("malformed instance name")
    try:
        number = DEFAULT_PORT if port in (None, "") else int(port)
    except (TypeError, ValueError):
        raise ValueError("malformed port") from None
    if not 0 < number < 65536:
        raise ValueError("port out of range")
    name = f"{server}\\{instance}" if instance else server
    return f"{name}:{number}"


def server_fingerprint(host: str | None, port: int | str | None) -> str:
    return hashlib.sha256(normalize_server(host, port).encode("utf-8")).hexdigest()


def approved_fingerprints(environ: Mapping[str, str]) -> frozenset[str]:
    """Approved values from the process environment (comma-separated). Fail closed."""
    raw = (environ.get(APPROVED_SERVER_ENV) or "").strip()
    if not raw:
        raise WrongServerError(
            f"Integration tests refused: {APPROVED_SERVER_ENV} is not set in this shell "
            "(see docs/UAT-P1-M2.md §2a)."
        )
    values = [v.strip().lower() for v in raw.split(",")]
    if not all(_SHA256_HEX.match(v) for v in values):
        raise WrongServerError(
            f"Integration tests refused: {APPROVED_SERVER_ENV} must be one or more "
            "64-character SHA-256 hex values separated by commas."
        )
    return frozenset(values)


def check_server_targets(urls: Mapping[str, str], environ: Mapping[str, str]) -> None:
    """Raise unless every connection URL points at an approved server. Never connects."""
    approved = approved_fingerprints(environ)
    problems: list[str] = []
    for role in sorted(urls):
        try:
            url = make_url(urls[role])
            fingerprint = server_fingerprint(url.host, url.port)
        except (ArgumentError, ValueError, TypeError):
            problems.append(f"{role}: server cannot be determined from the URL")
            continue
        if fingerprint not in approved:
            problems.append(f"{role}: server is not the approved sav_uat server")
    if problems:
        raise WrongServerError("Integration tests refused: " + "; ".join(problems) + ".")


class WrongDatabaseError(WrongServerError):
    """The configured connection does not point at the approved database."""


def check_database_names(names: dict[str, str | None]) -> None:
    """Raise unless every connection reports `sav_uat` (case-insensitive, as SQL Server)."""
    wrong = {
        role: name
        for role, name in names.items()
        if (name or "").strip().casefold() != EXPECTED_DATABASE.casefold()
    }
    if wrong:
        found = ", ".join(f"{role}={name!r}" for role, name in sorted(wrong.items()))
        raise WrongDatabaseError(
            f"Integration tests refused: connected database must be '{EXPECTED_DATABASE}', "
            f"found {found}. Fix DB_WRITER_URL / DB_READER_URL in your .env."
        )


async def read_database_names() -> dict[str, str | None]:
    """`SELECT DB_NAME()` on the writer and reader engines (read-only), then dispose them."""
    from sqlalchemy import text

    from app.core.database import dispose_engines, get_db_session

    names: dict[str, str | None] = {}
    try:
        for role, use_reader in (("writer", False), ("reader", True)):
            async with get_db_session(use_reader=use_reader) as session:
                try:
                    names[role] = (await session.execute(text("SELECT DB_NAME()"))).scalar()
                finally:
                    await session.rollback()
    finally:
        await dispose_engines()
    return names


def _main() -> None:  # pragma: no cover - interactive helper
    print("Fingerprint of the approved UAT server (typed here, not read from .env).")  # noqa: T201
    host = input("Host (DNS name, IP or host\\instance): ")
    port = input(f"Port [{DEFAULT_PORT}]: ")
    try:
        print(server_fingerprint(host, port or None))  # noqa: T201
    except ValueError as exc:
        print(f"Not a valid server: {exc}")  # noqa: T201


if __name__ == "__main__":  # pragma: no cover
    _main()
