"""Tests for the Decimal field.

Money and other fixed-precision values must not be modelled as ``Float`` (binary
float drift). The ``Decimal`` field stores ``decimal.Decimal``, validates
optional precision/scale, and string-encodes in payloads so there is no float
round-trip.
"""

import decimal

import pytest

from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import Decimal
from protean.utils.reflection import declared_fields


class Money(BaseValueObject):
    amount: Decimal(precision=19, scale=4, min_value=0)


class PlainMoney(BaseValueObject):
    amount: Decimal()


@pytest.mark.parametrize(
    "value,expected",
    [
        ("10.25", decimal.Decimal("10.25")),
        (10, decimal.Decimal("10")),
        (decimal.Decimal("3.1400"), decimal.Decimal("3.1400")),
    ],
)
def test_decimal_coercion(value, expected):
    vo = Money(amount=value)
    assert isinstance(vo.amount, decimal.Decimal)
    assert vo.amount == expected


def test_decimal_arithmetic_is_exact():
    vo = Money(amount="0.10")
    # The float drift this field exists to avoid: 0.1 + 0.2 != 0.3 in float.
    assert vo.amount + decimal.Decimal("0.20") == decimal.Decimal("0.30")


def test_scale_is_validated():
    with pytest.raises(ValidationError):
        Money(amount="1.123456")  # 6 dp exceeds scale=4


def test_min_value_is_validated():
    with pytest.raises(ValidationError):
        Money(amount="-5")


def test_serialized_as_string():
    """Field-level serialization must string-encode the Decimal (no float)."""
    field = declared_fields(Money)["amount"]
    encoded = field.as_dict(decimal.Decimal("10.2500"))
    assert encoded == "10.2500"
    assert isinstance(encoded, str)


def test_precision_scale_carried_on_resolved_field():
    """The adapter layer reads precision/scale to build NUMERIC(p, s)."""
    field = declared_fields(Money)["amount"]
    assert field.precision == 19
    assert field.scale == 4


def test_precision_scale_optional():
    field = declared_fields(PlainMoney)["amount"]
    assert field.precision is None
    assert field.scale is None
    vo = PlainMoney(amount="123456789.123456789")
    assert vo.amount == decimal.Decimal("123456789.123456789")
