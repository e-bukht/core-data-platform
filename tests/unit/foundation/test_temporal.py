from datetime import UTC, date, datetime, timedelta

import pytest

from core_platform.foundation.temporal import DateRange, InstantRange, Version


def test_date_range_is_end_exclusive() -> None:
    interval = DateRange(date(2026, 1, 1), date(2026, 2, 1))
    assert interval.contains(date(2026, 1, 31))
    assert not interval.contains(date(2026, 2, 1))


def test_date_range_rejects_empty_range() -> None:
    with pytest.raises(ValueError):
        DateRange(date(2026, 1, 1), date(2026, 1, 1))


def test_instant_range_requires_timezone() -> None:
    with pytest.raises(ValueError):
        InstantRange(datetime(2026, 1, 1), datetime(2026, 1, 2))


def test_instant_range_contains_timezone_aware_instant() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    interval = InstantRange(start, start + timedelta(hours=1))
    assert interval.contains(start + timedelta(minutes=30))


def test_version_next() -> None:
    assert Version(4).next() == Version(5)
