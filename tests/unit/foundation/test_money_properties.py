from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from core_platform.foundation.money import CurrencyCode, Money


@given(
    st.decimals(allow_nan=False, allow_infinity=False),
    st.decimals(allow_nan=False, allow_infinity=False),
)
def test_money_addition_preserves_exact_decimal_values(left: Decimal, right: Decimal) -> None:
    currency = CurrencyCode("XOF")
    assert Money(left, currency).add(Money(right, currency)).amount == left + right
