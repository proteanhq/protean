"""Association and embedded fields declared in the typed-annotation style.

``entries: list[Entry] = HasMany(Entry)`` must behave like
``entries = HasMany(Entry)``: the descriptor owns the field, and the type
annotation is only there for type checkers.
"""

from typing import Any

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject
from protean.fields import (
    Float,
    HasMany,
    HasOne,
    Reference,
    String,
    ValueObject,
)
from protean.utils.reflection import attributes, declared_fields


# Defined before the aggregates so the unquoted annotations can name them.
class Entry(BaseEntity):
    sku: str = String(required=True)


class Note(BaseEntity):
    text: str | None = String()


class Money(BaseValueObject):
    amount: float | None = Float()
    currency: str | None = String(max_length=3)


class Cart(BaseAggregate):
    """Unquoted annotations naming classes that already exist."""

    name: str | None = String()
    entries: list[Entry] = HasMany(Entry)
    note: Note | None = HasOne(Note)
    total: Money | None = ValueObject(Money)


class Basket(BaseAggregate):
    """Quoted inner names, as written for forward references."""

    name: str | None = String()
    lines: list["Line"] = HasMany("Line")
    memo: "Memo | None" = HasOne("Memo")
    total: "Money | None" = ValueObject("Money")


class Line(BaseEntity):
    sku: str = String(required=True)


class Memo(BaseEntity):
    text: str | None = String()


class Crate(BaseAggregate):
    """The whole annotation quoted."""

    name: str | None = String()
    parts: "list[Part]" = HasMany("Part")


class Part(BaseEntity):
    sku: str = String(required=True)


class Shipment(BaseAggregate):
    """An entity that owns a ``HasMany`` in the typed-annotation style."""

    tracking_id: str | None = String()
    order: "Order | None" = HasOne("Order")


class Order(BaseEntity):
    reference: str | None = String()
    items: list["OrderItem"] = HasMany("OrderItem")
    shipment: "Shipment | None" = Reference("Shipment")


class OrderItem(BaseEntity):
    sku: str = String(required=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Cart)
    test_domain.register(Entry, part_of=Cart)
    test_domain.register(Note, part_of=Cart)
    test_domain.register(Money)
    test_domain.register(Basket)
    test_domain.register(Line, part_of=Basket)
    test_domain.register(Memo, part_of=Basket)
    test_domain.register(Crate)
    test_domain.register(Part, part_of=Crate)
    test_domain.register(Shipment)
    test_domain.register(Order, part_of=Shipment)
    test_domain.register(OrderItem, part_of=Order)
    test_domain.init(traverse=False)


# (aggregate class, field name, child entity class)
HAS_MANY_FORMS = [
    pytest.param(Cart, "entries", Entry, id="unquoted"),
    pytest.param(Basket, "lines", Line, id="quoted-inner"),
    pytest.param(Crate, "parts", Part, id="quoted-whole"),
]

HAS_ONE_FORMS = [
    pytest.param(Cart, "note", Note, id="unquoted"),
    pytest.param(Basket, "memo", Memo, id="quoted"),
]


class TestFieldDeclaration:
    @pytest.mark.parametrize("aggregate_cls, field_name, child_cls", HAS_MANY_FORMS)
    def test_has_many_is_a_descriptor_and_not_a_pydantic_field(
        self, aggregate_cls: Any, field_name: str, child_cls: Any
    ) -> None:
        field = declared_fields(aggregate_cls)[field_name]
        assert isinstance(field, HasMany)
        assert field.to_cls is child_cls
        assert field_name not in aggregate_cls.model_fields

    @pytest.mark.parametrize("aggregate_cls, field_name, child_cls", HAS_ONE_FORMS)
    def test_has_one_is_a_descriptor_and_not_a_pydantic_field(
        self, aggregate_cls: Any, field_name: str, child_cls: Any
    ) -> None:
        field = declared_fields(aggregate_cls)[field_name]
        assert isinstance(field, HasOne)
        assert field.to_cls is child_cls
        assert field_name not in aggregate_cls.model_fields

    @pytest.mark.parametrize("aggregate_cls", [Cart, Basket])
    def test_value_object_is_a_descriptor_with_shadow_fields(
        self, aggregate_cls: Any
    ) -> None:
        assert isinstance(declared_fields(aggregate_cls)["total"], ValueObject)
        assert "total" not in aggregate_cls.model_fields
        assert "total_amount" in attributes(aggregate_cls)
        assert "total_currency" in attributes(aggregate_cls)

    def test_reference_is_a_descriptor_with_a_shadow_field(self) -> None:
        field = declared_fields(Order)["shipment"]
        assert isinstance(field, Reference)
        assert field.to_cls is Shipment
        assert "shipment" not in Order.model_fields
        assert "shipment_id" in attributes(Order)

    def test_entity_owned_has_many_is_a_descriptor(self) -> None:
        field = declared_fields(Order)["items"]
        assert isinstance(field, HasMany)
        assert field.to_cls is OrderItem
        assert "items" not in Order.model_fields


class TestConstruction:
    @pytest.mark.parametrize("aggregate_cls, field_name, child_cls", HAS_MANY_FORMS)
    def test_has_many_is_optional_and_defaults_to_empty_list(
        self, aggregate_cls: Any, field_name: str, child_cls: Any
    ) -> None:
        aggregate = aggregate_cls()
        assert getattr(aggregate, field_name) == []

    @pytest.mark.parametrize("aggregate_cls, field_name, child_cls", HAS_MANY_FORMS)
    def test_has_many_accepts_a_list_of_entities(
        self, aggregate_cls: Any, field_name: str, child_cls: Any
    ) -> None:
        children = [child_cls(sku="a"), child_cls(sku="b")]
        aggregate = aggregate_cls(**{field_name: children})

        assert [c.sku for c in getattr(aggregate, field_name)] == ["a", "b"]
        assert aggregate.to_dict()[field_name] == [c.to_dict() for c in children]

    @pytest.mark.parametrize("aggregate_cls, field_name, child_cls", HAS_ONE_FORMS)
    def test_has_one_is_optional(
        self, aggregate_cls: Any, field_name: str, child_cls: Any
    ) -> None:
        aggregate = aggregate_cls()
        assert getattr(aggregate, field_name) is None

    @pytest.mark.parametrize("aggregate_cls, field_name, child_cls", HAS_ONE_FORMS)
    def test_has_one_accepts_an_entity(
        self, aggregate_cls: Any, field_name: str, child_cls: Any
    ) -> None:
        child = child_cls(text="hello")
        aggregate = aggregate_cls(**{field_name: child})

        assert getattr(aggregate, field_name) == child
        assert aggregate.to_dict()[field_name] == child.to_dict()

    def test_value_object_sets_shadow_fields(self) -> None:
        cart = Cart(total=Money(amount=10.5, currency="USD"))

        assert cart.total == Money(amount=10.5, currency="USD")
        assert cart.total_amount == 10.5
        assert cart.total_currency == "USD"
        assert cart.to_dict()["total"] == {"amount": 10.5, "currency": "USD"}

    def test_value_object_is_optional(self) -> None:
        assert Cart().total is None

    def test_entity_owned_has_many_and_reference(self) -> None:
        order = Order(reference="o-1", items=[OrderItem(sku="a")])
        shipment = Shipment(tracking_id="t-1", order=order)

        assert order.items[0].order_id == order.id
        assert order.shipment_id == shipment.id
        assert shipment.to_dict()["order"]["items"] == [order.items[0].to_dict()]

    def test_entity_owned_has_many_defaults_to_empty_list(self) -> None:
        assert Order().items == []


class TestAddAndRemove:
    @pytest.mark.parametrize("aggregate_cls, field_name, child_cls", HAS_MANY_FORMS)
    def test_add_and_remove(
        self, aggregate_cls: Any, field_name: str, child_cls: Any
    ) -> None:
        aggregate = aggregate_cls()
        child = child_cls(sku="a")

        getattr(aggregate, f"add_{field_name}")(child)
        assert getattr(aggregate, field_name) == [child]

        getattr(aggregate, f"remove_{field_name}")(child)
        assert getattr(aggregate, field_name) == []


class TestPersistence:
    @pytest.mark.parametrize("aggregate_cls, field_name, child_cls", HAS_MANY_FORMS)
    def test_has_many_round_trips_through_repository(
        self, test_domain, aggregate_cls: Any, field_name: str, child_cls: Any
    ) -> None:
        aggregate = aggregate_cls(
            name="x", **{field_name: [child_cls(sku="a"), child_cls(sku="b")]}
        )
        test_domain.repository_for(aggregate_cls).add(aggregate)

        loaded = test_domain.repository_for(aggregate_cls).get(aggregate.id)
        assert sorted(c.sku for c in getattr(loaded, field_name)) == ["a", "b"]

    @pytest.mark.parametrize("aggregate_cls, field_name, child_cls", HAS_ONE_FORMS)
    def test_has_one_round_trips_through_repository(
        self, test_domain, aggregate_cls: Any, field_name: str, child_cls: Any
    ) -> None:
        aggregate = aggregate_cls(name="x", **{field_name: child_cls(text="hi")})
        test_domain.repository_for(aggregate_cls).add(aggregate)

        loaded = test_domain.repository_for(aggregate_cls).get(aggregate.id)
        assert getattr(loaded, field_name).text == "hi"

    def test_value_object_round_trips_through_repository(self, test_domain) -> None:
        cart = Cart(name="x", total=Money(amount=3.0, currency="EUR"))
        test_domain.repository_for(Cart).add(cart)

        loaded = test_domain.repository_for(Cart).get(cart.id)
        assert loaded.total == Money(amount=3.0, currency="EUR")

    def test_nested_has_many_round_trips_through_repository(self, test_domain) -> None:
        shipment = Shipment(
            tracking_id="t-1",
            order=Order(reference="o-1", items=[OrderItem(sku="a")]),
        )
        test_domain.repository_for(Shipment).add(shipment)

        loaded = test_domain.repository_for(Shipment).get(shipment.id)
        assert [i.sku for i in loaded.order.items] == ["a"]
        assert loaded.order.shipment_id == shipment.id


class TestDecoratedPlainClasses:
    """Plain classes go through the decorator's namespace preparation first."""

    def test_has_many_and_has_one_on_decorated_classes(self, test_domain) -> None:
        @test_domain.aggregate
        class Wishlist:
            items: list["WishItem"] = HasMany("WishItem")
            pin: "WishPin | None" = HasOne("WishPin")

        @test_domain.entity(part_of=Wishlist)
        class WishItem:
            sku: str = String(required=True)

        @test_domain.entity(part_of=Wishlist)
        class WishPin:
            label: str | None = String()

        test_domain.init(traverse=False)

        assert Wishlist().items == []
        assert Wishlist().pin is None

        wishlist = Wishlist(items=[WishItem(sku="a")], pin=WishPin(label="top"))
        assert [i.sku for i in wishlist.items] == ["a"]
        assert wishlist.pin.label == "top"
