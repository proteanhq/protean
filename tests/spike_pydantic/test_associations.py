"""PoC tests for HasMany[T] and HasOne[T] associations (Pydantic native).

Validates:
- HasMany[T] / HasOne[T] detected during __init_subclass__ (or model_post_init)
- Associations stored in PrivateAttr _associations
- Accessible via __getattr__
- Add/remove operations
- Change tracking (temp_cache concept)
- Not part of model_dump() or model_json_schema()
"""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import Field

from tests.spike_pydantic.base_classes import (
    HasMany,
    HasOne,
    ProteanAggregate,
    ProteanEntity,
)


# ---------------------------------------------------------------------------
# Test Entities
# ---------------------------------------------------------------------------
class OrderItem(ProteanEntity):
    id: UUID = Field(default_factory=uuid4)
    product_name: str
    quantity: int = Field(ge=1)
    unit_price: float = Field(ge=0)


class ShippingInfo(ProteanEntity):
    id: UUID = Field(default_factory=uuid4)
    carrier: str
    tracking_number: str = ""


class Comment(ProteanEntity):
    id: UUID = Field(default_factory=uuid4)
    text: str
    author: str


# ---------------------------------------------------------------------------
# Test Aggregate with Associations
# ---------------------------------------------------------------------------
class Order(ProteanAggregate):
    id: UUID = Field(default_factory=uuid4)
    order_number: str
    total: float = 0.0

    # Association fields - these should be detected and stored in _associations
    items: HasMany[OrderItem]
    shipping: HasOne[ShippingInfo]


class Post(ProteanAggregate):
    id: UUID = Field(default_factory=uuid4)
    title: str
    body: str = ""

    comments: HasMany[Comment]


# ---------------------------------------------------------------------------
# Tests: Association Setup
# ---------------------------------------------------------------------------
class TestAssociationDetection:
    """HasMany/HasOne annotations should be detected and set up."""

    def test_has_many_initialized(self):
        order = Order(order_number="ORD-001")
        # items should be an empty list
        assert order.items == []

    def test_has_one_initialized(self):
        order = Order(order_number="ORD-001")
        # shipping should be None
        assert order.shipping is None

    def test_associations_in_private_dict(self):
        order = Order(order_number="ORD-001")
        assert "items" in order._associations
        assert "shipping" in order._associations

    def test_associations_not_in_model_fields(self):
        """Association markers should NOT be regular Pydantic fields."""
        assert "items" not in Order.model_fields
        assert "shipping" not in Order.model_fields


class TestHasMany:
    """HasMany association operations."""

    def test_add_item(self):
        order = Order(order_number="ORD-001")
        item = OrderItem(product_name="Widget", quantity=2, unit_price=9.99)
        order._associations["items"].append(item)
        assert len(order.items) == 1
        assert order.items[0].product_name == "Widget"

    def test_add_multiple_items(self):
        order = Order(order_number="ORD-001")
        order._associations["items"].append(
            OrderItem(product_name="Widget", quantity=2, unit_price=9.99)
        )
        order._associations["items"].append(
            OrderItem(product_name="Gadget", quantity=1, unit_price=19.99)
        )
        assert len(order.items) == 2

    def test_remove_item(self):
        order = Order(order_number="ORD-001")
        item = OrderItem(product_name="Widget", quantity=2, unit_price=9.99)
        order._associations["items"].append(item)
        assert len(order.items) == 1
        order._associations["items"].remove(item)
        assert len(order.items) == 0

    def test_iterate_items(self):
        order = Order(order_number="ORD-001")
        for name in ["Widget", "Gadget", "Thingamajig"]:
            order._associations["items"].append(
                OrderItem(product_name=name, quantity=1, unit_price=5.0)
            )
        names = [item.product_name for item in order.items]
        assert names == ["Widget", "Gadget", "Thingamajig"]

    def test_items_are_independent(self):
        """Different aggregate instances have independent association lists."""
        o1 = Order(order_number="ORD-001")
        o2 = Order(order_number="ORD-002")
        o1._associations["items"].append(
            OrderItem(product_name="Widget", quantity=1, unit_price=5.0)
        )
        assert len(o1.items) == 1
        assert len(o2.items) == 0


class TestHasOne:
    """HasOne association operations."""

    def test_set_has_one(self):
        order = Order(order_number="ORD-001")
        shipping = ShippingInfo(carrier="FedEx", tracking_number="FX123")
        order._associations["shipping"] = shipping
        assert order.shipping is not None
        assert order.shipping.carrier == "FedEx"

    def test_replace_has_one(self):
        order = Order(order_number="ORD-001")
        order._associations["shipping"] = ShippingInfo(carrier="FedEx")
        order._associations["shipping"] = ShippingInfo(carrier="UPS")
        assert order.shipping.carrier == "UPS"

    def test_clear_has_one(self):
        order = Order(order_number="ORD-001")
        order._associations["shipping"] = ShippingInfo(carrier="FedEx")
        order._associations["shipping"] = None
        assert order.shipping is None


class TestAssociationNotInDump:
    """Associations stored in PrivateAttr should not appear in model_dump."""

    def test_not_in_dump(self):
        order = Order(order_number="ORD-001")
        order._associations["items"].append(
            OrderItem(product_name="Widget", quantity=1, unit_price=5.0)
        )
        data = order.model_dump()
        assert "items" not in data
        assert "shipping" not in data
        assert "_associations" not in data

    def test_not_in_schema(self):
        schema = Order.model_json_schema()
        props = schema.get("properties", {})
        assert "items" not in props
        assert "shipping" not in props
        assert "_associations" not in props


class TestAssociationOwnership:
    """Child entities should track their root aggregate."""

    def test_child_root_set(self):
        """When adding a child, its _root should point to the aggregate.

        Note: In the full implementation, add_* methods would set _root.
        For this PoC, we manually set it to prove PrivateAttr works.
        """
        order = Order(order_number="ORD-001")
        item = OrderItem(product_name="Widget", quantity=1, unit_price=5.0)
        # In full impl, add_items() would do this:
        item._root = order
        item._owner = order
        order._associations["items"].append(item)

        assert item._root is order
        assert item._owner is order


class TestMultipleAssociations:
    """Aggregates with only HasMany."""

    def test_post_with_comments(self):
        post = Post(title="Hello World", body="Content here")
        assert post.comments == []

        c1 = Comment(text="Great post!", author="Alice")
        c2 = Comment(text="Thanks!", author="Bob")
        post._associations["comments"].append(c1)
        post._associations["comments"].append(c2)

        assert len(post.comments) == 2
        assert post.comments[0].author == "Alice"
