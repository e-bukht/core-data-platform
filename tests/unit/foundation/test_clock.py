from __future__ import annotations

from datetime import UTC, datetime

from core_platform.foundation.temporal import Clock, UtcClock


def _read_clock(clock: Clock) -> datetime:
    return clock.now()


def test_utc_clock_returns_timezone_aware_utc_instant() -> None:
    before = datetime.now(UTC)

    instant = _read_clock(UtcClock())

    after = datetime.now(UTC)

    assert instant.tzinfo is UTC
    assert before <= instant <= after


def test_clock_protocol_allows_deterministic_test_double() -> None:
    expected = datetime(2026, 9, 26, 17, 0, tzinfo=UTC)

    class FixedClock:
        def now(self) -> datetime:
            return expected

    assert _read_clock(FixedClock()) == expected
