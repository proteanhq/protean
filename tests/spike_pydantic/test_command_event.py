"""PoC tests for ProteanCommand and ProteanEvent (Pydantic native).

Validates:
- Frozen model blocks mutation
- PrivateAttr _metadata set in model_post_init (mutable on frozen)
- payload property returns model_dump()
- Field validation works
- Extra fields rejected
- JSON Schema generation
"""

from __future__ import annotations

import enum
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from pydantic import Field, ValidationError

from tests.spike_pydantic.base_classes import (
    ProteanCommand,
    ProteanEvent,
)


# ---------------------------------------------------------------------------
# Test Commands
# ---------------------------------------------------------------------------
class PlaceOrder(ProteanCommand):
    order_id: UUID
    customer_name: str
    items: list[dict]


class RegisterUser(ProteanCommand):
    username: Annotated[str, Field(min_length=3, max_length=50)]
    email: str
    age: int = Field(ge=18)


# ---------------------------------------------------------------------------
# Test Events
# ---------------------------------------------------------------------------
class OrderStatus(str, enum.Enum):
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"


class OrderPlaced(ProteanEvent):
    order_id: UUID
    order_number: str
    total: float
    status: OrderStatus = OrderStatus.PLACED


class UserRegistered(ProteanEvent):
    user_id: UUID
    username: str
    email: str


# ---------------------------------------------------------------------------
# Command Tests
# ---------------------------------------------------------------------------
class TestCommandCreation:
    def test_create_command(self):
        uid = uuid4()
        cmd = PlaceOrder(
            order_id=uid,
            customer_name="Alice",
            items=[{"product": "Widget", "qty": 2}],
        )
        assert cmd.order_id == uid
        assert cmd.customer_name == "Alice"
        assert len(cmd.items) == 1

    def test_command_frozen(self):
        cmd = PlaceOrder(
            order_id=uuid4(),
            customer_name="Alice",
            items=[],
        )
        with pytest.raises(ValidationError):
            cmd.customer_name = "Bob"

    def test_command_validation(self):
        with pytest.raises(ValidationError) as exc_info:
            RegisterUser(username="ab", email="a@b.com", age=18)  # min_length=3
        assert "username" in str(exc_info.value)

    def test_command_age_validation(self):
        with pytest.raises(ValidationError) as exc_info:
            RegisterUser(username="alice", email="a@b.com", age=17)  # ge=18
        assert "age" in str(exc_info.value)

    def test_command_extra_rejected(self):
        with pytest.raises(ValidationError):
            PlaceOrder(
                order_id=uuid4(),
                customer_name="Alice",
                items=[],
                unknown="bad",
            )


class TestCommandMetadata:
    """_metadata PrivateAttr set in model_post_init."""

    def test_metadata_set(self):
        cmd = PlaceOrder(order_id=uuid4(), customer_name="Alice", items=[])
        assert cmd._metadata["kind"] == "COMMAND"
        assert cmd._metadata["type"] == "PlaceOrder"

    def test_metadata_mutable_on_frozen(self):
        """PrivateAttrs must be mutable even on frozen model."""
        cmd = PlaceOrder(order_id=uuid4(), customer_name="Alice", items=[])
        cmd._metadata["extra_key"] = "extra_value"
        assert cmd._metadata["extra_key"] == "extra_value"

    def test_metadata_not_in_dump(self):
        cmd = PlaceOrder(order_id=uuid4(), customer_name="Alice", items=[])
        data = cmd.model_dump()
        assert "_metadata" not in data

    def test_metadata_not_in_schema(self):
        schema = PlaceOrder.model_json_schema()
        assert "_metadata" not in schema.get("properties", {})


class TestCommandPayload:
    """payload property returns model_dump()."""

    def test_payload(self):
        uid = uuid4()
        cmd = PlaceOrder(order_id=uid, customer_name="Alice", items=[{"p": "w"}])
        payload = cmd.payload
        assert payload["order_id"] == str(uid) or payload["order_id"] == uid
        assert payload["customer_name"] == "Alice"
        assert payload["items"] == [{"p": "w"}]


class TestCommandSchema:
    def test_schema_structure(self):
        schema = PlaceOrder.model_json_schema()
        assert schema["type"] == "object"
        assert "order_id" in schema["properties"]
        assert "customer_name" in schema["properties"]
        assert "items" in schema["properties"]

    def test_schema_uuid_format(self):
        schema = PlaceOrder.model_json_schema()
        order_id_props = schema["properties"]["order_id"]
        assert order_id_props.get("format") == "uuid"

    def test_schema_constraints(self):
        schema = RegisterUser.model_json_schema()
        username_props = schema["properties"]["username"]
        assert username_props.get("minLength") == 3
        assert username_props.get("maxLength") == 50
        age_props = schema["properties"]["age"]
        assert age_props.get("minimum") == 18


# ---------------------------------------------------------------------------
# Event Tests
# ---------------------------------------------------------------------------
class TestEventCreation:
    def test_create_event(self):
        uid = uuid4()
        event = OrderPlaced(order_id=uid, order_number="ORD-001", total=99.99)
        assert event.order_id == uid
        assert event.order_number == "ORD-001"
        assert event.total == 99.99
        assert event.status == OrderStatus.PLACED

    def test_event_frozen(self):
        event = OrderPlaced(order_id=uuid4(), order_number="ORD-001", total=99.99)
        with pytest.raises(ValidationError):
            event.total = 200.0

    def test_event_extra_rejected(self):
        with pytest.raises(ValidationError):
            OrderPlaced(
                order_id=uuid4(),
                order_number="ORD-001",
                total=99.99,
                unknown="bad",
            )


class TestEventMetadata:
    def test_metadata_set(self):
        event = OrderPlaced(order_id=uuid4(), order_number="ORD-001", total=99.99)
        assert event._metadata["kind"] == "EVENT"
        assert event._metadata["type"] == "OrderPlaced"

    def test_metadata_mutable_on_frozen(self):
        event = OrderPlaced(order_id=uuid4(), order_number="ORD-001", total=99.99)
        event._metadata["stream"] = "order-123"
        assert event._metadata["stream"] == "order-123"

    def test_metadata_not_in_dump(self):
        event = OrderPlaced(order_id=uuid4(), order_number="ORD-001", total=99.99)
        data = event.model_dump()
        assert "_metadata" not in data


class TestEventPayload:
    def test_payload(self):
        uid = uuid4()
        event = OrderPlaced(order_id=uid, order_number="ORD-001", total=99.99)
        payload = event.payload
        assert payload["order_number"] == "ORD-001"
        assert payload["total"] == 99.99

    def test_payload_with_enum(self):
        event = OrderPlaced(order_id=uuid4(), order_number="ORD-001", total=99.99)
        payload = event.payload
        # Pydantic serializes enums to their value by default
        assert payload["status"] in ("PLACED", OrderStatus.PLACED)


class TestEventSchema:
    def test_schema_structure(self):
        schema = OrderPlaced.model_json_schema()
        assert schema["type"] == "object"
        assert "order_id" in schema["properties"]
        assert "order_number" in schema["properties"]
        assert "total" in schema["properties"]
        assert "status" in schema["properties"]

    def test_schema_enum(self):
        schema = OrderPlaced.model_json_schema()
        # Enum should appear in schema
        status_props = schema["properties"]["status"]
        # Could be $ref or inline, check for enum values
        if "$ref" in status_props:
            # Look in $defs
            assert "$defs" in schema
            assert "OrderStatus" in schema["$defs"]
        else:
            assert "enum" in status_props

    def test_schema_default(self):
        schema = OrderPlaced.model_json_schema()
        required = schema.get("required", [])
        # status has a default, so should not be required
        assert "status" not in required


class TestRoundTrip:
    """Serialize and deserialize commands and events."""

    def test_command_round_trip(self):
        uid = uuid4()
        cmd = PlaceOrder(order_id=uid, customer_name="Alice", items=[{"p": "w"}])
        data = cmd.model_dump()
        cmd2 = PlaceOrder(**data)
        assert cmd2.order_id == uid
        assert cmd2.customer_name == "Alice"

    def test_event_round_trip(self):
        uid = uuid4()
        event = OrderPlaced(order_id=uid, order_number="ORD-001", total=99.99)
        data = event.model_dump()
        event2 = OrderPlaced(**data)
        assert event2.order_id == uid
        assert event2.order_number == "ORD-001"
        assert event2.total == 99.99
