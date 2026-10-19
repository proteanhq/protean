"""Typed-annotation association and value object fields, on every provider.

``items: list[Item] = HasMany(Item)``, ``label: Label | None = HasOne(Label)``
and ``price: Price | None = ValueObject(Price)`` persist and load the same way
as their assignment-style forms.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject
from protean.fields import Float, HasMany, HasOne, Reference, String, ValueObject


class Price(BaseValueObject):
    amount: float | None = Float()
    currency: str | None = String(max_length=3)


class Parcel(BaseAggregate):
    name: str = String(max_length=50, required=True)
    items: list["ParcelItem"] = HasMany("ParcelItem")
    label: "ParcelLabel | None" = HasOne("ParcelLabel")
    price: Price | None = ValueObject(Price)


class ParcelItem(BaseEntity):
    sku: str = String(max_length=50, required=True)
    parcel: "Parcel | None" = Reference("Parcel")


class ParcelLabel(BaseEntity):
    text: str | None = String(max_length=50)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Price)
    test_domain.register(Parcel)
    test_domain.register(ParcelItem, part_of=Parcel)
    test_domain.register(ParcelLabel, part_of=Parcel)
    test_domain.init(traverse=False)


@pytest.mark.basic_storage
class TestTypedAnnotationPersistence:
    def test_aggregate_with_no_children_round_trips(self, test_domain):
        parcel = Parcel(name="empty")
        test_domain.repository_for(Parcel).add(parcel)

        loaded = test_domain.repository_for(Parcel).get(parcel.id)
        assert loaded.items == []
        assert loaded.label is None
        assert loaded.price is None

    def test_children_and_value_object_round_trip(self, test_domain):
        parcel = Parcel(
            name="full",
            items=[ParcelItem(sku="a"), ParcelItem(sku="b")],
            label=ParcelLabel(text="fragile"),
            price=Price(amount=9.5, currency="USD"),
        )
        test_domain.repository_for(Parcel).add(parcel)

        loaded = test_domain.repository_for(Parcel).get(parcel.id)
        assert sorted(i.sku for i in loaded.items) == ["a", "b"]
        assert all(i.parcel_id == parcel.id for i in loaded.items)
        assert loaded.label.text == "fragile"
        assert loaded.price == Price(amount=9.5, currency="USD")

    def test_add_and_remove_children_on_a_loaded_aggregate(self, test_domain):
        parcel = Parcel(name="growing", items=[ParcelItem(sku="a")])
        test_domain.repository_for(Parcel).add(parcel)

        loaded = test_domain.repository_for(Parcel).get(parcel.id)
        loaded.add_items(ParcelItem(sku="b"))
        loaded.remove_items(next(i for i in loaded.items if i.sku == "a"))
        test_domain.repository_for(Parcel).add(loaded)

        reloaded = test_domain.repository_for(Parcel).get(parcel.id)
        assert [i.sku for i in reloaded.items] == ["b"]
