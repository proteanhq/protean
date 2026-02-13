"""PoC tests for ProteanEntity and ProteanAggregate (Pydantic native).

Validates:
- Mutable model with validate_assignment
- __setattr__ override runs invariant checks and state tracking
- PrivateAttr for internal state (_root, _owner, _state, _events)
- _EntityState lifecycle tracking
- Aggregate versioning and event raising
- Identity-based equality
- Extra fields rejected
- model_dump() and model_json_schema()
"""

from __future__ import annotations

import enum
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from pydantic import Field, ValidationError

from tests.spike_pydantic.base_classes import (
    ProteanAggregate,
    ProteanEntity,
    ProteanValueObject,
    invariant,
)


# ---------------------------------------------------------------------------
# Test VOs for embedding
# ---------------------------------------------------------------------------
class Address(ProteanValueObject):
    street: str
    city: str
    zip_code: str


# ---------------------------------------------------------------------------
# Test Entities and Aggregates
# ---------------------------------------------------------------------------
class OrderStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class OrderItem(ProteanEntity):
    id: UUID = Field(default_factory=uuid4)
    product_name: str
    quantity: int = Field(ge=1)
    unit_price: float = Field(ge=0)


class Order(ProteanAggregate):
    id: UUID = Field(default_factory=uuid4)
    order_number: Annotated[str, Field(max_length=50)]
    total: float = 0.0
    status: OrderStatus = OrderStatus.DRAFT
    shipping_address: Address | None = None

    @invariant.post
    def total_must_not_be_negative(self):
        if self.total < 0:
            from protean.exceptions import ValidationError as PValidationError

            raise PValidationError({"total": ["must not be negative"]})

    @invariant.pre
    def cannot_modify_cancelled_order(self):
        if self.status == OrderStatus.CANCELLED:
            from protean.exceptions import ValidationError as PValidationError

            raise PValidationError({"_entity": ["cannot modify a cancelled order"]})


class SimpleEntity(ProteanEntity):
    id: UUID = Field(default_factory=uuid4)
    name: str
    value: int = 0


# ---------------------------------------------------------------------------
# Entity Tests
# ---------------------------------------------------------------------------
class TestEntityCreation:
    def test_create_entity(self):
        item = OrderItem(product_name="Widget", quantity=2, unit_price=9.99)
        assert item.product_name == "Widget"
        assert item.quantity == 2
        assert item.unit_price == 9.99
        assert item.id is not None  # auto-generated

    def test_entity_with_explicit_id(self):
        uid = uuid4()
        item = OrderItem(id=uid, product_name="Widget", quantity=2, unit_price=9.99)
        assert item.id == uid

    def test_entity_validation(self):
        with pytest.raises(ValidationError):
            OrderItem(product_name="Widget", quantity=0, unit_price=9.99)  # ge=1

    def test_entity_extra_rejected(self):
        with pytest.raises(ValidationError):
            OrderItem(product_name="Widget", quantity=1, unit_price=9.99, unknown="bad")


class TestEntityMutation:
    """Entities are mutable with validate_assignment."""

    def test_mutate_field(self):
        item = OrderItem(product_name="Widget", quantity=2, unit_price=9.99)
        item.product_name = "Gadget"
        assert item.product_name == "Gadget"

    def test_mutation_validates(self):
        """validate_assignment ensures constraints on mutation."""
        item = OrderItem(product_name="Widget", quantity=2, unit_price=9.99)
        with pytest.raises(ValidationError):
            item.quantity = 0  # ge=1 violation

    def test_mutation_type_check(self):
        item = OrderItem(product_name="Widget", quantity=2, unit_price=9.99)
        with pytest.raises(ValidationError):
            item.quantity = "not_a_number"


class TestEntityState:
    """_EntityState lifecycle tracking."""

    def test_new_entity_is_new(self):
        item = OrderItem(product_name="Widget", quantity=2, unit_price=9.99)
        assert item._state.is_new is True
        assert item._state.is_changed is False
        assert item._state.is_persisted is False
        assert item._state.is_destroyed is False

    def test_mark_saved(self):
        item = OrderItem(product_name="Widget", quantity=2, unit_price=9.99)
        item._state.mark_saved()
        assert item._state.is_new is False
        assert item._state.is_persisted is True

    def test_mutation_marks_changed(self):
        """__setattr__ override should mark state as changed."""
        entity = SimpleEntity(name="test", value=1)
        assert entity._state.is_changed is False
        entity.value = 2
        assert entity._state.is_changed is True

    def test_mark_destroyed(self):
        item = OrderItem(product_name="Widget", quantity=2, unit_price=9.99)
        item._state.mark_destroyed()
        assert item._state.is_destroyed is True


class TestEntityEquality:
    """Identity-based equality."""

    def test_same_id_equal(self):
        uid = uuid4()
        e1 = SimpleEntity(id=uid, name="one", value=1)
        e2 = SimpleEntity(id=uid, name="two", value=2)
        assert e1 == e2

    def test_different_id_not_equal(self):
        e1 = SimpleEntity(name="same", value=1)
        e2 = SimpleEntity(name="same", value=1)
        assert e1 != e2  # Different auto-generated IDs

    def test_different_type_not_equal(self):
        uid = uuid4()
        e1 = SimpleEntity(id=uid, name="test")
        i1 = OrderItem(id=uid, product_name="Widget", quantity=1, unit_price=1.0)
        assert e1 != i1

    def test_hashable(self):
        uid = uuid4()
        e1 = SimpleEntity(id=uid, name="test")
        e2 = SimpleEntity(id=uid, name="test")
        assert hash(e1) == hash(e2)
        s = {e1, e2}
        assert len(s) == 1


# ---------------------------------------------------------------------------
# Aggregate Tests
# ---------------------------------------------------------------------------
class TestAggregateCreation:
    def test_create_aggregate(self):
        order = Order(order_number="ORD-001")
        assert order.order_number == "ORD-001"
        assert order.total == 0.0
        assert order.status == OrderStatus.DRAFT
        assert order.id is not None

    def test_aggregate_with_nested_vo(self):
        addr = Address(street="123 Main", city="NYC", zip_code="10001")
        order = Order(order_number="ORD-001", shipping_address=addr)
        assert order.shipping_address.street == "123 Main"

    def test_aggregate_nested_vo_from_dict(self):
        order = Order(
            order_number="ORD-001",
            shipping_address={"street": "123 Main", "city": "NYC", "zip_code": "10001"},
        )
        assert isinstance(order.shipping_address, Address)
        assert order.shipping_address.city == "NYC"


class TestAggregateRootSetup:
    """Aggregate sets _root = self."""

    def test_root_is_self(self):
        order = Order(order_number="ORD-001")
        assert order._root is order

    def test_owner_is_self(self):
        order = Order(order_number="ORD-001")
        assert order._owner is order


class TestAggregateMutation:
    def test_mutate_field(self):
        order = Order(order_number="ORD-001")
        order.total = 99.99
        assert order.total == 99.99

    def test_mutation_validates(self):
        order = Order(order_number="ORD-001")
        with pytest.raises(ValidationError):
            order.order_number = "X" * 51  # max_length=50

    def test_mutation_marks_changed(self):
        order = Order(order_number="ORD-001")
        assert order._state.is_changed is False
        order.total = 99.99
        assert order._state.is_changed is True


class TestAggregateInvariants:
    """Invariant checks via __setattr__ override."""

    def test_post_invariant_on_init(self):
        """Post-invariants run after __init__."""
        from protean.exceptions import ValidationError as PValidationError

        with pytest.raises(PValidationError) as exc_info:
            Order(order_number="ORD-001", total=-5.0)
        assert "total" in exc_info.value.messages

    def test_post_invariant_on_mutation(self):
        """Post-invariants run after field mutation via __setattr__."""
        order = Order(order_number="ORD-001", total=10.0)

        from protean.exceptions import ValidationError as PValidationError

        with pytest.raises(PValidationError) as exc_info:
            order.total = -1.0
        assert "total" in exc_info.value.messages

    def test_pre_invariant_on_mutation(self):
        """Pre-invariants run before field mutation via __setattr__."""
        Order(order_number="ORD-001", status=OrderStatus.CANCELLED)
        # Wait - this will fail at init because post-invariant checks total.
        # Let's set it up properly:
        order2 = Order(order_number="ORD-002", total=10.0)
        order2.status = OrderStatus.CANCELLED

        from protean.exceptions import ValidationError as PValidationError

        with pytest.raises(PValidationError) as exc_info:
            order2.total = 20.0  # should trigger pre-invariant
        assert "_entity" in exc_info.value.messages


class TestAggregateEvents:
    """Event raising on aggregates."""

    def test_raise_event(self):
        order = Order(order_number="ORD-001")
        event = {"type": "OrderPlaced", "order_id": str(order.id)}
        order.raise_(event)
        assert len(order._events) == 1
        assert order._events[0] == event

    def test_multiple_events(self):
        order = Order(order_number="ORD-001")
        order.raise_({"type": "OrderPlaced"})
        order.raise_({"type": "OrderConfirmed"})
        assert len(order._events) == 2


class TestAggregateVersioning:
    def test_initial_version(self):
        order = Order(order_number="ORD-001")
        assert order._version == -1
        assert order._next_version == 0


class TestEntityPrivateAttrsNotInSchema:
    """Internal PrivateAttrs should NOT appear in schema or dump."""

    def test_private_attrs_not_in_dump(self):
        order = Order(order_number="ORD-001")
        data = order.model_dump()
        assert "_state" not in data
        assert "_root" not in data
        assert "_owner" not in data
        assert "_events" not in data
        assert "_version" not in data
        assert "_initialized" not in data
        assert "_invariants" not in data
        assert "_associations" not in data
        assert "_temp_cache" not in data

    def test_private_attrs_not_in_schema(self):
        schema = Order.model_json_schema()
        props = schema.get("properties", {})
        assert "_state" not in props
        assert "_root" not in props
        assert "_owner" not in props
        assert "_events" not in props
        assert "_version" not in props

    def test_model_fields_correct(self):
        """model_fields should only contain declared fields."""
        assert "id" in Order.model_fields
        assert "order_number" in Order.model_fields
        assert "total" in Order.model_fields
        assert "status" in Order.model_fields
        assert "_state" not in Order.model_fields
        assert "_root" not in Order.model_fields


class TestEntitySerialization:
    def test_model_dump(self):
        uid = uuid4()
        order = Order(id=uid, order_number="ORD-001", total=99.99)
        data = order.model_dump()
        assert data["id"] == uid
        assert data["order_number"] == "ORD-001"
        assert data["total"] == 99.99

    def test_model_dump_with_nested_vo(self):
        order = Order(
            order_number="ORD-001",
            shipping_address=Address(street="123 Main", city="NYC", zip_code="10001"),
        )
        data = order.model_dump()
        assert data["shipping_address"]["street"] == "123 Main"

    def test_round_trip(self):
        uid = uuid4()
        order = Order(id=uid, order_number="ORD-001", total=99.99)
        data = order.model_dump()
        order2 = Order(**data)
        assert order2.id == uid
        assert order2.order_number == "ORD-001"


class TestEntitySchema:
    def test_schema_structure(self):
        schema = Order.model_json_schema()
        assert schema["type"] == "object"
        assert "id" in schema["properties"]
        assert "order_number" in schema["properties"]
        assert "total" in schema["properties"]
        assert "status" in schema["properties"]

    def test_schema_constraints(self):
        schema = Order.model_json_schema()
        assert schema["properties"]["order_number"].get("maxLength") == 50

    def test_entity_schema(self):
        schema = OrderItem.model_json_schema()
        assert schema["type"] == "object"
        assert "product_name" in schema["properties"]
        assert "quantity" in schema["properties"]
        qty_props = schema["properties"]["quantity"]
        assert qty_props.get("minimum") == 1
