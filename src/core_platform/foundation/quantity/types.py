from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

_UNIT_RE = re.compile(r"^[A-Z][A-Z0-9_.-]{0,31}$")


@dataclass(frozen=True, slots=True, order=True)
class UnitCode:
    value: str

    def __post_init__(self) -> None:
        if not _UNIT_RE.fullmatch(self.value):
            raise ValueError("invalid unit code")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Quantity:
    value: Decimal
    unit: UnitCode
