"""
Legacy time and identifier conventions (U01 plan P1.4).

cp-web writes **India local time** into legacy `datetime` columns:
`DateTime.UtcNow.ToIndiaDateTime()` → `TimeZoneInfo.ConvertTimeFromUtc(utc, "India Standard
Time")` [Code `CrystalPower.Infrastructure/Helpers/Time.cs:22-34`]. The result is a naive
local datetime. India has had a fixed UTC+05:30 offset with no daylight saving since 1945,
so a fixed offset gives the same value as the Windows time zone (and needs no tz database
on Windows).

Use these helpers for every legacy table. Never use the Phase 2 UTC helpers
(`app.models.base.AuditColumnsMixin`) on legacy tables.
"""

from datetime import UTC, datetime, timedelta, timezone
import uuid


IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def india_now() -> datetime:
    """Naive India local time, like `DateTime.UtcNow.ToIndiaDateTime()`."""
    return datetime.now(UTC).astimezone(IST).replace(tzinfo=None)


def to_india(utc_value: datetime) -> datetime:
    """Convert an aware or naive-UTC datetime to naive India local time."""
    if utc_value.tzinfo is None:
        utc_value = utc_value.replace(tzinfo=UTC)
    return utc_value.astimezone(IST).replace(tzinfo=None)


def new_legacy_guid() -> uuid.UUID:
    """App-generated row Guid, like `Guid.NewGuid()` in cp-web (no database default)."""
    return uuid.uuid4()
