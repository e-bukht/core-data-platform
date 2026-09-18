from decimal import Decimal

import pytest

from core_platform.foundation.money import CurrencyCode, CurrencyMismatch, Money


def test_money_adds_same_currency() -> None:
    xof = CurrencyCode("XOF")
    assert Money(Decimal("100.10"), xof).add(Money(Decimal("1.90"), xof)) == Money(
        Decimal("102.00"), xof
    )


def test_money_rejects_cross_currency_arithmetic() -> None:
    with pytest.raises(CurrencyMismatch):
        Money(Decimal("1"), CurrencyCode("XOF")).add(Money(Decimal("1"), CurrencyCode("EUR")))


@pytest.mark.parametrize("raw", ["xof", "EURO", "12", ""])
def test_currency_code_validation(raw: str) -> None:
    with pytest.raises(ValueError):
        CurrencyCode(raw)
