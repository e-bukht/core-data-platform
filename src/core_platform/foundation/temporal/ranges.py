from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime


@dataclass(frozen=True, slots=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError("DateRange requires start < end")

    def contains(self, value: date) -> bool:
        return self.start <= value < self.end


@dataclass(frozen=True, slots=True)
class InstantRange:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("InstantRange requires timezone-aware datetimes")
        if self.start >= self.end:
            raise ValueError("InstantRange requires start < end")

    @staticmethod
    def normalize(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")
        return value.astimezone(UTC)

    def contains(self, value: datetime) -> bool:
        normalized = self.normalize(value)
        return self.normalize(self.start) <= normalized < self.normalize(self.end)
