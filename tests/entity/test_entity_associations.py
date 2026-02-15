"""Tests for association support on BaseEntity / BaseAggregate.

Validates:
- HasMany: add/remove/access, pseudo-methods, change tracking
- HasOne: assign/replace/None
- Reference: back-reference field, auto-generated ID
- Root/owner propagation
- __container_fields__ bridge
- to_dict() serialization (Reference skipped)
- Domain registration with part_of
"""

from uuid import uuid4

import pytest
from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.fields import HasMany, HasOne, Reference
from protean.utils import fully_qualified_name
from protean.utils.reflection import (
    _FIELDS,
    association_fields,
)


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------
class Order(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    order_number: str = ""
    items = HasMany("tests.entity.test_entity_associations.OrderItem")
    shipping = HasOne("tests.entity.test_entity_associations.ShippingInfo")


class OrderItem(BaseEntity):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    product_name: str = ""
    quantity: int = 1
    order = Reference("tests.entity.test_entity_associations.Order")


class ShippingInfo(BaseEntity):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    address: str = ""
    order = Reference("tests.entity.test_entity_associations.Order")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderItem, part_of=Order)
    test_domain.register(ShippingInfo, part_of=Order)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Tests: __container_fields__ bridge
# ---------------------------------------------------------------------------
class TestContainerFieldsBridge:
    def test_annotated_fields_in_container_fields(self):
        cf = getattr(Order, _FIELDS, {})
        assert "id" in cf
        assert "order_number" in cf

    def test_has_many_descriptor_in_container_fields(self):
        cf = getattr(Order, _FIELDS, {})
        assert "items" in cf
        assert isinstance(cf["items"], HasMany)

    def test_has_one_descriptor_in_container_fields(self):
        cf = getattr(Order, _FIELDS, {})
        assert "shipping" in cf
        assert isinstance(cf["shipping"], HasOne)

    def test_reference_descriptor_in_container_fields(self):
        cf = getattr(OrderItem, _FIELDS, {})
        assert "order" in cf
        assert isinstance(cf["order"], Reference)

    def test_association_fields_utility(self):
        af = association_fields(Order)
        assert "items" in af
        assert "shipping" in af
        # Regular model fields should not appear in association_fields
        assert "order_number" not in af


# ---------------------------------------------------------------------------
# Tests: HasMany
# ---------------------------------------------------------------------------
class TestHasMany:
    def test_construct_with_has_many_list(self):
        item1 = OrderItem(product_name="Widget", quantity=2)
        item2 = OrderItem(product_name="Gadget", quantity=1)
        order = Order(order_number="ORD-001", items=[item1, item2])

        assert len(order.items) == 2
        assert order.items[0].product_name == "Widget"
        assert order.items[1].product_name == "Gadget"

    def test_has_many_empty_by_default(self):
        order = Order(order_number="ORD-002")
        assert order.items == []

    def test_add_pseudo_method(self):
        order = Order(order_number="ORD-003")
        item = OrderItem(product_name="Widget", quantity=3)
        order.add_items(item)

        assert len(order.items) == 1
        assert order.items[0].product_name == "Widget"

    def test_add_multiple_via_pseudo_method(self):
        order = Order(order_number="ORD-004")
        item1 = OrderItem(product_name="Widget")
        item2 = OrderItem(product_name="Gadget")
        order.add_items([item1, item2])

        assert len(order.items) == 2

    def test_remove_pseudo_method(self):
        item1 = OrderItem(product_name="Widget")
        item2 = OrderItem(product_name="Gadget")
        order = Order(order_number="ORD-005", items=[item1, item2])

        order.remove_items(item1)
        assert len(order.items) == 1
        assert order.items[0].product_name == "Gadget"

    def test_back_reference_set_on_children(self):
        item = OrderItem(product_name="Widget")
        order = Order(order_number="ORD-006", items=[item])

        assert item.order_id == order.id

    def test_temp_cache_tracks_added_items(self):
        order = Order(order_number="ORD-007")
        item = OrderItem(product_name="Widget")
        order.add_items(item)

        assert "items" in order._temp_cache
        assert "added" in order._temp_cache["items"]


# ---------------------------------------------------------------------------
# Tests: HasOne
# ---------------------------------------------------------------------------
class TestHasOne:
    def test_construct_with_has_one(self):
        shipping = ShippingInfo(address="123 Main St")
        order = Order(order_number="ORD-010", shipping=shipping)

        assert order.shipping == shipping
        assert order.shipping.address == "123 Main St"

    def test_has_one_none_by_default(self):
        order = Order(order_number="ORD-011")
        assert order.shipping is None

    def test_replace_has_one(self):
        shipping1 = ShippingInfo(address="123 Main St")
        order = Order(order_number="ORD-012", shipping=shipping1)

        shipping2 = ShippingInfo(address="456 Elm Ave")
        order.shipping = shipping2

        assert order.shipping.address == "456 Elm Ave"

    def test_back_reference_set_on_has_one_child(self):
        shipping = ShippingInfo(address="123 Main St")
        order = Order(order_number="ORD-013", shipping=shipping)

        assert shipping.order_id == order.id


# ---------------------------------------------------------------------------
# Tests: Root/Owner propagation
# ---------------------------------------------------------------------------
class TestRootAndOwner:
    def test_has_many_children_have_root(self):
        item = OrderItem(product_name="Widget")
        order = Order(order_number="ORD-020", items=[item])

        assert item._root == order

    def test_has_many_children_have_owner(self):
        item = OrderItem(product_name="Widget")
        order = Order(order_number="ORD-021", items=[item])

        assert item._owner == order

    def test_has_one_child_has_root(self):
        shipping = ShippingInfo(address="123 Main St")
        order = Order(order_number="ORD-022", shipping=shipping)

        assert shipping._root == order

    def test_has_one_child_has_owner(self):
        shipping = ShippingInfo(address="123 Main St")
        order = Order(order_number="ORD-023", shipping=shipping)

        assert shipping._owner == order


# ---------------------------------------------------------------------------
# Tests: State tracking
# ---------------------------------------------------------------------------
class TestStateTracking:
    def test_adding_has_many_updates_temp_cache(self):
        order = Order(order_number="ORD-030")
        item = OrderItem(product_name="Widget")
        order.add_items(item)

        # HasMany.add tracks changes in _temp_cache
        assert "items" in order._temp_cache
        assert "added" in order._temp_cache["items"]
        assert len(order._temp_cache["items"]["added"]) == 1

    def test_setting_has_one_marks_changed(self):
        order = Order(order_number="ORD-031")
        order._state.mark_saved()
        assert not order._state.is_changed

        order.shipping = ShippingInfo(address="123 Main St")

        assert order._state.is_changed


# ---------------------------------------------------------------------------
# Tests: Serialization
# ---------------------------------------------------------------------------
class TestSerialization:
    def test_to_dict_includes_has_many(self):
        item = OrderItem(product_name="Widget", quantity=2)
        order = Order(order_number="ORD-040", items=[item])
        d = order.to_dict()

        assert "items" in d
        assert len(d["items"]) == 1
        assert d["items"][0]["product_name"] == "Widget"

    def test_to_dict_includes_has_one(self):
        shipping = ShippingInfo(address="123 Main St")
        order = Order(order_number="ORD-041", shipping=shipping)
        d = order.to_dict()

        assert "shipping" in d
        assert d["shipping"]["address"] == "123 Main St"

    def test_to_dict_skips_reference_fields(self):
        item = OrderItem(product_name="Widget")
        d = item.to_dict()

        # Reference field should not appear in to_dict
        assert "order" not in d
        # Shadow field (order_id) is also not in to_dict — it is in attributes()
        assert "order_id" not in d

    def test_to_dict_empty_has_many(self):
        order = Order(order_number="ORD-042")
        d = order.to_dict()

        assert d["items"] == []

    def test_to_dict_none_has_one(self):
        order = Order(order_number="ORD-043")
        d = order.to_dict()

        assert d["shipping"] is None


# ---------------------------------------------------------------------------
# Tests: Domain registration
# ---------------------------------------------------------------------------
class TestDomainRegistration:
    def test_aggregate_with_associations_registered(self, test_domain):
        assert fully_qualified_name(Order) in test_domain.registry.aggregates

    def test_child_entity_registered_as_part_of(self, test_domain):
        assert fully_qualified_name(OrderItem) in test_domain.registry.entities

    def test_has_one_entity_registered_as_part_of(self, test_domain):
        assert fully_qualified_name(ShippingInfo) in test_domain.registry.entities
