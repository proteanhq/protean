import enum
from datetime import date, datetime
from decimal import Decimal as D
from ipaddress import IPv4Address
from typing import Annotated, Literal, NewType

import pytest
from pydantic import (
    AfterValidator,
    BeforeValidator,
    PlainSerializer,
    PlainValidator,
    WrapValidator,
    model_validator,
)
from pydantic import Field as PydanticField
from typing_extensions import TypeAliasType

from protean.core.value_object import (
    BaseValueObject,
    _value_hashed_field_names,
)
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
from protean.fields.spec import FieldSpec


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
    if isinstance(field, FieldSpec):
        return type(name, (BaseValueObject,), {"value": field})
    # A raw annotation, such as ``Annotated[T, PlainValidator(...)]``
    return type(name, (BaseValueObject,), {"__annotations__": {"value": field}})


class Level(enum.Enum):
    LOW = "low"
    HIGH = "high"


class UnhashableDecimal(D):
    """Equal to the ``Decimal`` of the same amount, but unhashable."""

    def __eq__(self, other: object) -> bool:
        return D.__eq__(self, other)

    __hash__ = None  # type: ignore[assignment]


def _keep_unhashable_decimal(value):
    return value if isinstance(value, D) else UnhashableDecimal(str(value))


class Cash(BaseValueObject):
    kind: Literal["cash"] = "cash"
    amount: Decimal()


class Card(BaseValueObject):
    kind: Literal["card"] = "card"
    amount: Decimal()


# Pydantic resolves this alias through a definition that refers to itself.
NoneAlias = TypeAliasType("NoneAlias", "NoneAlias | None")


# The space ``__hash__`` decides over, one row per cell. A field is hashed by
# value only when Pydantic's core schema for it bounds every value it can
# store to types whose hash agrees with ``==``; any other field adds a
# constant. The cells:
#
# - the schema's output type: a built-in scalar, ``None``, a ``Literal`` or
#   ``Status``, an optional or other union of those, a nested value object, a
#   container, a custom type, or a type alias of any of these;
# - the validators around the cast: none, a ``BeforeValidator``, Protean's own
#   after-validators, a user ``AfterValidator``, or a ``PlainValidator`` or
#   ``WrapValidator`` that replaces the cast, on a ``Custom`` field or a raw
#   ``Annotated`` declaration;
# - annotation metadata that cannot be hashed, at any depth;
# - the stored values: equal or unequal, of the same or different types,
#   hashable or not.
#
# Columns: case, field factory, first value, second value, whether the two
# value objects are equal, whether the field is hashed by value.
HASH_SPACE = [
    ("string", lambda: String(), "a", "a", True, True),
    ("string-differs", lambda: String(), "a", "b", False, True),
    ("text", lambda: Text(), "a", "a", True, True),
    ("identifier", lambda: Identifier(), "id-1", "id-1", True, True),
    ("integer", lambda: Integer(), 1, 1, True, True),
    ("integer-differs", lambda: Integer(), 1, 2, False, True),
    ("float", lambda: Float(), 1.5, 1.5, True, True),
    (
        "decimal-scaled",
        lambda: Decimal(precision=19, scale=4),
        D("9.99"),
        D("9.9900"),
        True,
        True,
    ),
    ("decimal-unscaled", lambda: Decimal(), D("1.0"), D(1), True, True),
    ("decimal-differs", lambda: Decimal(), D("9.99"), D("9.98"), False, True),
    ("boolean", lambda: Boolean(), True, True, True, True),
    ("date", lambda: Date(), date(2026, 1, 1), date(2026, 1, 1), True, True),
    (
        "datetime",
        lambda: DateTime(),
        datetime(2026, 1, 1),
        datetime(2026, 1, 1),
        True,
        True,
    ),
    ("status", lambda: Status(Level), "low", "low", True, True),
    ("none-both", lambda: String(), None, None, True, True),
    ("none-one", lambda: String(), None, "a", False, True),
    ("list", lambda: List(content_type=Decimal()), [D("1.0")], [D(1)], True, False),
    ("list-differs", lambda: List(content_type=Integer()), [1], [2], False, False),
    ("dict", lambda: Dict(), {"a": D("1.0")}, {"a": D(1)}, True, False),
    (
        "nested-vo",
        lambda: ValueObject(Inner),
        Inner(amount=D("1.0")),
        Inner(amount=D(1)),
        True,
        True,
    ),
    (
        "nested-vo-none",
        lambda: ValueObject(Inner),
        None,
        Inner(amount=D(1)),
        False,
        True,
    ),
    ("custom-unhashable", lambda: _custom(Color), "#00ff00", "#00FF00", True, False),
    (
        "custom-unhashable-differs",
        lambda: _custom(Color),
        "#00ff00",
        "#ff0000",
        False,
        False,
    ),
    ("custom-unhashable-scale", lambda: _custom(Money), "9.99", "9.9900", True, False),
    (
        "custom-mixed-hashability",
        lambda: _custom(Color),
        Color("#0f0"),
        HashableColor("#0F0"),
        True,
        False,
    ),
    ("custom-hashable", lambda: _custom(Code), "x", "x", True, False),
    ("custom-hashable-differs", lambda: _custom(Code), "x", "y", False, False),
    (
        "custom-decimal-parser-keeps-unhashable-subclass",
        lambda: Custom(D, validators=[PlainValidator(_keep_unhashable_decimal)]),
        UnhashableDecimal("9.99"),
        D("9.9900"),
        True,
        False,
    ),
    (
        "raw-annotated-decimal-plain-validator",
        lambda: Annotated[D, PlainValidator(_keep_unhashable_decimal)],
        UnhashableDecimal("1.0"),
        D(1),
        True,
        False,
    ),
    (
        "raw-annotated-decimal-wrap-validator",
        lambda: Annotated[D, WrapValidator(lambda v, _: _keep_unhashable_decimal(v))],
        UnhashableDecimal("1.0"),
        D(1),
        True,
        False,
    ),
    # Without a replacing validator, Pydantic casts a ``Decimal`` subclass to a
    # plain ``Decimal``, so the declared type still bounds the stored value.
    ("custom-decimal-no-validator", lambda: Custom(D), D("1.0"), D(1), True, True),
    (
        "custom-decimal-no-validator-differs",
        lambda: Custom(D),
        D("1.0"),
        D(2),
        False,
        True,
    ),
    (
        "decimal-given-unhashable-subclass",
        lambda: Decimal(),
        UnhashableDecimal("1.0"),
        D(1),
        True,
        True,
    ),
    ("literal", lambda: Literal["a", 1], "a", "a", True, True),
    ("literal-differs", lambda: Literal["a", 1], "a", 1, False, True),
    ("union-of-scalars", lambda: int | str, 1, 1, True, True),
    ("union-of-scalars-differs", lambda: int | str, 1, "1", False, True),
    ("union-with-container", lambda: int | list[int], [1], [1], True, False),
    ("new-type", lambda: NewType("Sku", str), "x", "x", True, True),
    (
        "tagged-union-of-vos",
        lambda: Annotated[Cash | Card, PydanticField(discriminator="kind")],
        Cash(amount=D("1.0")),
        Cash(amount=D(1)),
        True,
        True,
    ),
    (
        "tagged-union-of-vos-differs",
        lambda: Annotated[Cash | Card, PydanticField(discriminator="kind")],
        Cash(amount=D(1)),
        Card(amount=D(1)),
        False,
        True,
    ),
    # Pydantic wraps the instance check in ``lax-or-strict`` and
    # ``json-or-python`` schemas, which do not bound the stored type.
    (
        "ip-address",
        lambda: IPv4Address,
        IPv4Address("10.0.0.1"),
        IPv4Address("10.0.0.1"),
        True,
        False,
    ),
    ("self-referencing-alias", lambda: NoneAlias, None, None, True, False),
    ("new-type-differs", lambda: NewType("Sku", str), "x", "y", False, True),
    (
        "before-validator",
        lambda: Annotated[D, BeforeValidator(lambda v: _keep_unhashable_decimal(v))],
        UnhashableDecimal("1.0"),
        D(1),
        True,
        True,
    ),
    (
        "user-after-validator",
        lambda: Annotated[D, AfterValidator(lambda v: UnhashableDecimal(str(v)))],
        D("1.0"),
        D(1),
        True,
        False,
    ),
    (
        "unhashable-metadata-on-scalar",
        lambda: Annotated[int, {"unit": "items"}],
        1,
        1,
        True,
        True,
    ),
    (
        "unhashable-metadata-in-optional",
        lambda: Annotated[int, {"unit": "items"}] | None,
        1,
        1,
        True,
        True,
    ),
    (
        "unhashable-metadata-in-list",
        lambda: list[Annotated[int, {"unit": "items"}]],
        [1],
        [1],
        True,
        False,
    ),
    (
        "unhashable-metadata-in-list-differs",
        lambda: list[Annotated[int, {"unit": "items"}]],
        [1],
        [2],
        False,
        False,
    ),
]


@pytest.mark.parametrize(
    "case, make_field, first, second, equal, value_hashed",
    HASH_SPACE,
    ids=[row[0] for row in HASH_SPACE],
)
def test_equal_value_objects_hash_equal_across_field_types(
    case, make_field, first, second, equal, value_hashed
):
    vo_cls = _single_field_vo(f"VO_{case.replace('-', '_')}", make_field())
    a = vo_cls(value=first)
    b = vo_cls(value=second)

    assert ("value" in vo_cls._value_hashed_fields()) is value_hashed
    assert (a == b) is equal
    if equal:
        assert hash(a) == hash(b)
        assert len({a, b}) == 1
        assert {a: "found"}[b] == "found"
    elif value_hashed:
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


class _Validated(BaseValueObject):
    amount: Decimal()

    @model_validator(mode="after")
    def _check(self):
        return self


class _SharedInner(BaseValueObject):
    first = ValueObject(Inner)
    second = ValueObject(Inner)


class _Linked(BaseValueObject):
    amount: Decimal()
    next: "_Linked | None" = None


# Class shapes that change where Pydantic puts the field schemas: a model
# validator wraps them, a reused nested value object moves into shared
# definitions, and a self-reference resolves only after the class exists.
@pytest.mark.parametrize(
    "first, second, value_hashed",
    [
        (
            _Validated(amount=D("1.0")),
            _Validated(amount=D(1)),
            {"amount"},
        ),
        (
            _SharedInner(first=Inner(amount=D("1.0")), second=Inner(amount=D(2))),
            _SharedInner(first=Inner(amount=D(1)), second=Inner(amount=D("2.0"))),
            {"first", "second"},
        ),
        (
            _Linked(amount=D("1.0"), next=_Linked(amount=D(2))),
            _Linked(amount=D(1), next=_Linked(amount=D("2.0"))),
            {"amount", "next"},
        ),
    ],
    ids=["model-validator", "shared-definitions", "self-reference"],
)
def test_class_shape_does_not_change_field_hashing(first, second, value_hashed):
    assert type(first)._value_hashed_fields() == value_hashed
    assert first == second
    assert hash(first) == hash(second)


def test_model_schema_without_a_fields_node_hashes_no_field_by_value():
    assert _value_hashed_field_names({"type": "any"}) == frozenset()
