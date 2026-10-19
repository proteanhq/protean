"""The typed-annotation style declares the same fields as the assignment style.

Every field kind is declared twice, once as ``name = Field(...)`` and once as
``name: <type> = Field(...)``. Both domains must report the same field
classes, the same attributes, and the same IR.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest

from protean import Domain
from protean.fields import (
    Boolean,
    Date,
    DateTime,
    Dict,
    Float,
    HasMany,
    HasOne,
    Identifier,
    Integer,
    List,
    Reference,
    String,
    Text,
    ValueObject,
)
from protean.fields import Decimal as DecimalField
from protean.ir.builder import IRBuilder
from protean.utils.reflection import attributes, declared_fields


def _build_domain(typed: bool) -> tuple[Domain, dict[str, type]]:
    """Build the same model in one of the two styles.

    Both branches create classes with the same names and qualified names, so
    the IR of the two domains can be compared directly.
    """
    domain = Domain(name="Parity")

    @domain.value_object
    class Money:
        amount: int = Integer(required=True)
        currency: str | None = String(max_length=3)

    if typed:

        @domain.aggregate
        class Cart:
            s: str | None = String()
            t: str | None = Text()
            i: str | None = Identifier()
            n: int | None = Integer()
            f: float | None = Float()
            b: bool | None = Boolean()
            dd: date | None = Date()
            dt: datetime | None = DateTime()
            dec: Decimal | None = DecimalField()
            tags: list[str] = List(content_type=String())
            prices: list[Money] = List(content_type=ValueObject(Money))
            extra: dict[str, Any] = Dict()
            total: Money | None = ValueObject(Money)
            entries: list["Entry"] = HasMany("Entry")
            note: "Note | None" = HasOne("Note")

        @domain.entity(part_of=Cart)
        class Entry:
            sku: str = String(required=True)
            parts: list["Part"] = HasMany("Part")
            cart: "Cart | None" = Reference("Cart")

    else:

        @domain.aggregate
        class Cart:  # type: ignore[no-redef]
            s = String()
            t = Text()
            i = Identifier()
            n = Integer()
            f = Float()
            b = Boolean()
            dd = Date()
            dt = DateTime()
            dec = DecimalField()
            tags = List(content_type=String())
            prices = List(content_type=ValueObject(Money))
            extra = Dict()
            total = ValueObject(Money)
            entries = HasMany("Entry")
            note = HasOne("Note")

        @domain.entity(part_of=Cart)
        class Entry:  # type: ignore[no-redef]
            sku = String(required=True)
            parts = HasMany("Part")
            cart = Reference("Cart")

    @domain.entity(part_of=Cart)
    class Note:
        text: str | None = String()

    @domain.entity(part_of=Entry)
    class Part:
        code: str | None = String()

    domain.init(traverse=False)
    return domain, {"Cart": Cart, "Entry": Entry, "Note": Note, "Part": Part}


@pytest.fixture(scope="module")
def assigned() -> tuple[Domain, dict[str, type]]:
    return _build_domain(typed=False)


@pytest.fixture(scope="module")
def typed() -> tuple[Domain, dict[str, type]]:
    return _build_domain(typed=True)


@pytest.mark.no_test_domain
@pytest.mark.parametrize("element", ["Cart", "Entry", "Note", "Part"])
def test_declared_fields_have_the_same_classes(assigned, typed, element) -> None:
    assigned_fields = declared_fields(assigned[1][element])
    typed_fields = declared_fields(typed[1][element])

    assert len(assigned_fields) > 0
    # Compared as mappings: the auto-injected ``id`` lands at a different
    # position in the two styles, which is unrelated to the field classes.
    assert {name: type(f).__name__ for name, f in typed_fields.items()} == {
        name: type(f).__name__ for name, f in assigned_fields.items()
    }


@pytest.mark.no_test_domain
@pytest.mark.parametrize("element", ["Cart", "Entry", "Note", "Part"])
def test_attributes_match(assigned, typed, element) -> None:
    assert sorted(attributes(typed[1][element])) == sorted(
        attributes(assigned[1][element])
    )


@pytest.mark.no_test_domain
def test_value_object_and_reference_flatten_the_same_way(typed) -> None:
    assert {"total_amount", "total_currency"} <= set(attributes(typed[1]["Cart"]))
    assert "cart_id" in attributes(typed[1]["Entry"])


@pytest.mark.no_test_domain
def test_ir_matches(assigned, typed) -> None:
    assigned_ir = IRBuilder(assigned[0]).build()
    typed_ir = IRBuilder(typed[0]).build()

    assert assigned_ir["clusters"]
    assert typed_ir["clusters"] == assigned_ir["clusters"]
