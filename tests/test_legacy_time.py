from datetime import UTC, datetime, timedelta
import uuid

from app.core.legacy_time import india_now, new_legacy_guid, to_india


def test_india_now_is_naive_utc_plus_0530():
    before = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=5, minutes=30)
    value = india_now()
    after = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=5, minutes=30)
    assert value.tzinfo is None
    assert before <= value <= after


def test_to_india_handles_naive_utc_and_aware_values():
    utc = datetime(2026, 10, 23, 18, 40, 0)
    assert to_india(utc) == datetime(2026, 10, 24, 0, 10, 0)
    assert to_india(utc.replace(tzinfo=UTC)) == datetime(2026, 10, 24, 0, 10, 0)


def test_new_legacy_guid_is_random_uuid4():
    a, b = new_legacy_guid(), new_legacy_guid()
    assert isinstance(a, uuid.UUID) and a.version == 4 and a != b
