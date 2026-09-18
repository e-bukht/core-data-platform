from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True, slots=True, order=True)
class CurrencyCode:
    value: str

    def __post_init__(self) -> None:
        if not _CURRENCY_RE.fullmatch(self.value):
            raise ValueError("currency must be a 3-letter uppercase ISO-style code")

    def __str__(self) -> str:
        return self.value


class CurrencyMismatch(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: CurrencyCode

    def add(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def subtract(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def _require_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatch(f"{self.currency} != {other.currency}")
