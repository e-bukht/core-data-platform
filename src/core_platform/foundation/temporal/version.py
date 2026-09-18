from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, order=True)
class Version:
    value: int

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError("version must be >= 0")

    def next(self) -> Version:
        return Version(self.value + 1)
