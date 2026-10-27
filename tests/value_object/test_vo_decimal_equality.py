import enum
from datetime import date, datetime
from decimal import Decimal as D

import pytest
from pydantic import PlainSerializer, PlainValidator

from protean.core.value_object import BaseValueObject
from protean.fields import (
    Boolean,
    Custom,
    Date,
    DateTime,
    Decimal,
    Dict,
    Float,
    Identifier,
    Integer,
    List,
    Status,
    String,
    Text,
    ValueObject,
)


class Price(BaseValueObject):
    amount: Decimal(precision=19, scale=4, required=True)


class Quantity(BaseValueObject):
    amount: Decimal()


class OtherPrice(BaseValueObject):
    amount: Decimal(precision=19, scale=4, required=True)


class DiscountedPrice(Price):
    pass


class Inner(BaseValueObject):
    amount: Decimal()


class Outer(BaseValueObject):
    label: String(max_length=20)
    inner = ValueObject(Inner)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Price)
    test_domain.register(Quantity)
    test_domain.register(OtherPrice)
    test_domain.register(DiscountedPrice)
    test_domain.register(Inner)
    test_domain.register(Outer)
    test_domain.init(traverse=False)


class TestEqualDecimalsWithDifferentScales:
    def test_scaled_field_values_compare_and_hash_equal(self):
        a = Price(amount=D("9.99"))
        b = Price(amount=D("9.9900"))

        assert a == b
        assert hash(a) == hash(b)
        assert len({a, b}) == 1

    def test_unscaled_field_values_compare_and_hash_equal(self):
        a = Quantity(amount=D("1.0"))
        b = Quantity(amount=D(1))

        assert a == b
        assert hash(a) == hash(b)

    def test_nested_value_objects_compare_and_hash_equal(self):
        a = Outer(label="x", inner=Inner(amount=D("1.0")))
        b = Outer(label="x", inner=Inner(amount=D(1)))

        assert a == b
        assert hash(a) == hash(b)

    def test_nested_value_object_is_hashed_once_per_outer_hash(self, monkeypatch):
        calls = []
        original = Inner.__hash__

        def counting_hash(self):
            calls.append(self)
            return original(self)

        monkeypatch.setattr(Inner, "__hash__", counting_hash)

        hash(Outer(label="x", inner=Inner(amount=D("1.0"))))

        assert len(calls) == 1


class Color:
    """Defines ``__eq__`` without ``__hash__``, so instances are unhashable."""

    def __init__(self, value: str) -> None:
        self.hex = str(value).upper()

    def to_dict(self) -> str:
        return self.hex

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Color) and other.hex == self.hex


class HashableColor(Color):
    def __hash__(self) -> int:
        return hash(self.hex)


class Money:
    """Unhashable, and compares numerically while serializing with its scale."""

    def __init__(self, value: object) -> None:
        self.amount = D(str(value))

    def to_dict(self) -> str:
        return str(self.amount)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Money) and other.amount == self.amount


class Code:
    """Hashable custom type with value equality."""

    def __init__(self, value: str) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Code) and other.value == self.value

    def __hash__(self) -> int:
        return hash(self.value)


def _as(cls):
    def parse(value):
        return value if isinstance(value, cls) else cls(value)

    return parse


def _custom(cls):
    return Custom(
        cls,
        validators=[PlainValidator(_as(cls))],
        serializers=[PlainSerializer(str, return_type=str)],
    )


def _single_field_vo(name, field):
    return type(name, (BaseValueObject,), {"value": field})


class Level(enum.Enum):
    LOW = "low"
    HIGH = "high"


# One row per (declared field type, pair of values). Each row says whether the
# two values are equal; equal rows must also hash equal.
HASH_SPACE = [
    ("string", lambda: String(), "a", "a", True),
    ("string-differs", lambda: String(), "a", "b", False),
    ("text", lambda: Text(), "a", "a", True),
    ("identifier", lambda: Identifier(), "id-1", "id-1", True),
    ("integer", lambda: Integer(), 1, 1, True),
    ("integer-differs", lambda: Integer(), 1, 2, False),
    ("float", lambda: Float(), 1.5, 1.5, True),
    (
        "decimal-scaled",
        lambda: Decimal(precision=19, scale=4),
        D("9.99"),
        D("9.9900"),
        True,
    ),
    ("decimal-unscaled", lambda: Decimal(), D("1.0"), D(1), True),
    ("decimal-differs", lambda: Decimal(), D("9.99"), D("9.98"), False),
    ("boolean", lambda: Boolean(), True, True, True),
    ("date", lambda: Date(), date(2026, 1, 1), date(2026, 1, 1), True),
    ("datetime", lambda: DateTime(), datetime(2026, 1, 1), datetime(2026, 1, 1), True),
    ("status", lambda: Status(Level), "low", "low", True),
    ("none-both", lambda: String(), None, None, True),
    ("none-one", lambda: String(), None, "a", False),
    ("list", lambda: List(content_type=Decimal()), [D("1.0")], [D(1)], True),
    ("list-differs", lambda: List(content_type=Integer()), [1], [2], False),
    ("dict", lambda: Dict(), {"a": D("1.0")}, {"a": D(1)}, True),
    (
        "nested-vo",
        lambda: ValueObject(Inner),
        Inner(amount=D("1.0")),
        Inner(amount=D(1)),
        True,
    ),
    ("nested-vo-none", lambda: ValueObject(Inner), None, Inner(amount=D(1)), False),
    ("custom-unhashable", lambda: _custom(Color), "#00ff00", "#00FF00", True),
    ("custom-unhashable-differs", lambda: _custom(Color), "#00ff00", "#ff0000", False),
    ("custom-unhashable-scale", lambda: _custom(Money), "9.99", "9.9900", True),
    (
        "custom-mixed-hashability",
        lambda: _custom(Color),
        Color("#0f0"),
        HashableColor("#0F0"),
        True,
    ),
    ("custom-hashable", lambda: _custom(Code), "x", "x", True),
    ("custom-hashable-differs", lambda: _custom(Code), "x", "y", False),
]

# Rows whose field type hashes by value: unequal values should spread.
VALUE_HASHED_UNEQUAL = {
    "string-differs",
    "integer-differs",
    "decimal-differs",
    "none-one",
    "nested-vo-none",
}


@pytest.mark.parametrize(
    "case, make_field, first, second, equal",
    HASH_SPACE,
    ids=[row[0] for row in HASH_SPACE],
)
def test_equal_value_objects_hash_equal_across_field_types(
    case, make_field, first, second, equal
):
    vo_cls = _single_field_vo(f"VO_{case.replace('-', '_')}", make_field())
    a = vo_cls(value=first)
    b = vo_cls(value=second)

    assert (a == b) is equal
    if equal:
        assert hash(a) == hash(b)
        assert len({a, b}) == 1
        assert {a: "found"}[b] == "found"
    elif case in VALUE_HASHED_UNEQUAL:
        assert hash(a) != hash(b)


class TestUnequalValueObjects:
    def test_different_amounts_are_unequal(self):
        assert Price(amount=D("9.99")) != Price(amount=D("9.98"))

    def test_different_classes_with_same_values_are_unequal(self):
        assert Price(amount=D("9.99")) != OtherPrice(amount=D("9.99"))

    def test_subclass_with_same_values_is_unequal_to_parent(self):
        assert Price(amount=D("9.99")) != DiscountedPrice(amount=D("9.99"))

    def test_non_value_objects_are_unequal(self):
        price = Price(amount=D("9.99"))

        assert price != "x"
        assert price != None


def test_to_dict_keeps_the_given_scale():
    price = Price(amount=D("9.9900"))

    assert price.to_dict() == {"amount": "9.9900"}
    assert str(price.amount) == "9.9900"
