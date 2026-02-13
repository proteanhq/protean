"""PoC tests for JSON Schema generation across all element types.

Validates:
- model_json_schema() produces valid JSON Schema for all element types
- Schema includes correct types, constraints, formats, enums
- Nested VOs produce proper $defs references
- Schema excludes PrivateAttrs
- Schema can be used for external tool integration
"""

from __future__ import annotations

import enum
import json
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field

from tests.spike_pydantic.base_classes import (
    ProteanAggregate,
    ProteanCommand,
    ProteanEntity,
    ProteanEvent,
    ProteanProjection,
    ProteanValueObject,
)


# ---------------------------------------------------------------------------
# Test domain elements for schema generation
# ---------------------------------------------------------------------------
class Currency(str, enum.Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"


class Money(ProteanValueObject):
    amount: float = Field(ge=0, description="Monetary amount")
    currency: Currency = Currency.USD


class Address(ProteanValueObject):
    street: str = Field(description="Street address")
    city: str
    state: Annotated[str, Field(max_length=2)]
    zip_code: Annotated[str, Field(pattern=r"^\d{5}$")]
    country: str = "US"


class LineItem(ProteanEntity):
    id: UUID = Field(default_factory=uuid4)
    product_id: UUID
    product_name: str = Field(max_length=200)
    quantity: int = Field(ge=1, le=1000)
    unit_price: Money


class OrderStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class Order(ProteanAggregate):
    id: UUID = Field(default_factory=uuid4)
    order_number: Annotated[str, Field(max_length=50, pattern=r"^ORD-\d+$")]
    customer_email: str = Field(description="Customer email address")
    total: float = Field(ge=0, default=0.0)
    status: OrderStatus = OrderStatus.DRAFT
    billing_address: Address | None = None
    notes: list[str] = Field(default_factory=list)
    tags: dict[str, str] = Field(default_factory=dict)


class PlaceOrder(ProteanCommand):
    order_id: UUID
    customer_email: str
    items: list[dict]
    shipping_address: Address


class OrderPlaced(ProteanEvent):
    order_id: UUID
    order_number: str
    total: float
    status: OrderStatus


class OrderSummary(ProteanProjection):
    order_id: UUID
    order_number: str
    customer_email: str
    total: float
    status: str
    item_count: int = 0


# ---------------------------------------------------------------------------
# Tests: Value Object Schema
# ---------------------------------------------------------------------------
class TestValueObjectSchema:
    def test_basic_structure(self):
        schema = Money.model_json_schema()
        assert schema["title"] == "Money"
        assert schema["type"] == "object"

    def test_field_types(self):
        schema = Money.model_json_schema()
        amount = schema["properties"]["amount"]
        assert amount["type"] == "number"
        assert amount["minimum"] == 0
        assert amount.get("description") == "Monetary amount"

    def test_enum_in_schema(self):
        schema = Money.model_json_schema()
        # Currency enum should be in $defs or inline
        currency_prop = schema["properties"]["currency"]
        if "$ref" in currency_prop:
            # Enum is in $defs
            assert "$defs" in schema
            assert "Currency" in schema["$defs"]
        elif "allOf" in currency_prop:
            # Some Pydantic versions use allOf with $ref
            pass
        else:
            assert "enum" in currency_prop

    def test_default_in_schema(self):
        schema = Money.model_json_schema()
        # currency has a default
        required = schema.get("required", [])
        assert "currency" not in required

    def test_pattern_constraint(self):
        schema = Address.model_json_schema()
        zip_props = schema["properties"]["zip_code"]
        assert zip_props.get("pattern") == r"^\d{5}$"

    def test_max_length_constraint(self):
        schema = Address.model_json_schema()
        state_props = schema["properties"]["state"]
        assert state_props.get("maxLength") == 2

    def test_description(self):
        schema = Address.model_json_schema()
        street_props = schema["properties"]["street"]
        assert street_props.get("description") == "Street address"


# ---------------------------------------------------------------------------
# Tests: Entity Schema
# ---------------------------------------------------------------------------
class TestEntitySchema:
    def test_basic_structure(self):
        schema = LineItem.model_json_schema()
        assert schema["title"] == "LineItem"
        assert schema["type"] == "object"

    def test_id_field(self):
        schema = LineItem.model_json_schema()
        id_prop = schema["properties"]["id"]
        assert id_prop.get("format") == "uuid"

    def test_nested_vo_in_entity(self):
        schema = LineItem.model_json_schema()
        # unit_price is a nested Money VO
        assert "$defs" in schema
        assert "Money" in schema["$defs"]

    def test_range_constraints(self):
        schema = LineItem.model_json_schema()
        qty = schema["properties"]["quantity"]
        assert qty.get("minimum") == 1
        assert qty.get("maximum") == 1000

    def test_private_attrs_excluded(self):
        schema = LineItem.model_json_schema()
        props = schema.get("properties", {})
        assert "_state" not in props
        assert "_root" not in props
        assert "_owner" not in props


# ---------------------------------------------------------------------------
# Tests: Aggregate Schema
# ---------------------------------------------------------------------------
class TestAggregateSchema:
    def test_basic_structure(self):
        schema = Order.model_json_schema()
        assert schema["title"] == "Order"
        assert schema["type"] == "object"

    def test_all_fields_present(self):
        schema = Order.model_json_schema()
        props = schema["properties"]
        assert "id" in props
        assert "order_number" in props
        assert "customer_email" in props
        assert "total" in props
        assert "status" in props
        assert "billing_address" in props
        assert "notes" in props
        assert "tags" in props

    def test_optional_field(self):
        schema = Order.model_json_schema()
        # billing_address is Optional (Address | None)
        ba = schema["properties"]["billing_address"]
        # Pydantic represents Optional as anyOf with null
        if "anyOf" in ba:
            types = [t.get("type") for t in ba["anyOf"]]
            assert "null" in types
        # Or it might be handled differently

    def test_list_field(self):
        schema = Order.model_json_schema()
        notes = schema["properties"]["notes"]
        assert notes["type"] == "array"
        assert notes["items"]["type"] == "string"

    def test_dict_field(self):
        schema = Order.model_json_schema()
        tags = schema["properties"]["tags"]
        assert tags["type"] == "object"

    def test_pattern_constraint(self):
        schema = Order.model_json_schema()
        on = schema["properties"]["order_number"]
        assert on.get("maxLength") == 50
        assert on.get("pattern") == r"^ORD-\d+$"

    def test_nested_vo_in_defs(self):
        schema = Order.model_json_schema()
        assert "$defs" in schema
        assert "Address" in schema["$defs"]

    def test_private_attrs_excluded(self):
        schema = Order.model_json_schema()
        props = schema.get("properties", {})
        private_attrs = [
            "_state",
            "_root",
            "_owner",
            "_events",
            "_version",
            "_next_version",
            "_event_position",
            "_initialized",
            "_invariants",
            "_associations",
            "_temp_cache",
            "_meta",
        ]
        for attr in private_attrs:
            assert attr not in props, f"{attr} should not be in schema"


# ---------------------------------------------------------------------------
# Tests: Command Schema
# ---------------------------------------------------------------------------
class TestCommandSchema:
    def test_basic_structure(self):
        schema = PlaceOrder.model_json_schema()
        assert schema["title"] == "PlaceOrder"
        assert schema["type"] == "object"

    def test_nested_vo(self):
        schema = PlaceOrder.model_json_schema()
        assert "$defs" in schema
        assert "Address" in schema["$defs"]

    def test_list_of_dicts(self):
        schema = PlaceOrder.model_json_schema()
        items_prop = schema["properties"]["items"]
        assert items_prop["type"] == "array"

    def test_metadata_excluded(self):
        schema = PlaceOrder.model_json_schema()
        assert "_metadata" not in schema.get("properties", {})


# ---------------------------------------------------------------------------
# Tests: Event Schema
# ---------------------------------------------------------------------------
class TestEventSchema:
    def test_basic_structure(self):
        schema = OrderPlaced.model_json_schema()
        assert schema["title"] == "OrderPlaced"
        assert schema["type"] == "object"

    def test_enum_field(self):
        schema = OrderPlaced.model_json_schema()
        status_prop = schema["properties"]["status"]
        # Enum should be referenced
        assert "$ref" in status_prop or "allOf" in status_prop or "enum" in status_prop

    def test_metadata_excluded(self):
        schema = OrderPlaced.model_json_schema()
        assert "_metadata" not in schema.get("properties", {})


# ---------------------------------------------------------------------------
# Tests: Projection Schema
# ---------------------------------------------------------------------------
class TestProjectionSchema:
    def test_basic_structure(self):
        schema = OrderSummary.model_json_schema()
        assert schema["title"] == "OrderSummary"
        assert schema["type"] == "object"

    def test_all_fields_present(self):
        schema = OrderSummary.model_json_schema()
        props = schema["properties"]
        assert "order_id" in props
        assert "order_number" in props
        assert "customer_email" in props
        assert "total" in props
        assert "status" in props
        assert "item_count" in props

    def test_private_attrs_excluded(self):
        schema = OrderSummary.model_json_schema()
        assert "_state" not in schema.get("properties", {})
        assert "_meta" not in schema.get("properties", {})


# ---------------------------------------------------------------------------
# Tests: Schema Serialization
# ---------------------------------------------------------------------------
class TestSchemaSerializable:
    """JSON Schema should be serializable to JSON string."""

    def test_vo_schema_to_json(self):
        schema = Money.model_json_schema()
        json_str = json.dumps(schema)
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed == schema

    def test_aggregate_schema_to_json(self):
        schema = Order.model_json_schema()
        json_str = json.dumps(schema, indent=2)
        assert isinstance(json_str, str)

    def test_command_schema_to_json(self):
        schema = PlaceOrder.model_json_schema()
        json_str = json.dumps(schema)
        assert isinstance(json_str, str)

    def test_event_schema_to_json(self):
        schema = OrderPlaced.model_json_schema()
        json_str = json.dumps(schema)
        assert isinstance(json_str, str)


# ---------------------------------------------------------------------------
# Tests: Cross-Element Schema Comparison
# ---------------------------------------------------------------------------
class TestCrossElementSchema:
    """Schema structure should be consistent across element types."""

    def test_all_schemas_have_type_object(self):
        for cls in [
            Money,
            Address,
            LineItem,
            Order,
            PlaceOrder,
            OrderPlaced,
            OrderSummary,
        ]:
            schema = cls.model_json_schema()
            assert schema["type"] == "object", (
                f"{cls.__name__} schema missing type: object"
            )

    def test_all_schemas_have_properties(self):
        for cls in [
            Money,
            Address,
            LineItem,
            Order,
            PlaceOrder,
            OrderPlaced,
            OrderSummary,
        ]:
            schema = cls.model_json_schema()
            assert "properties" in schema, f"{cls.__name__} schema missing properties"

    def test_all_schemas_have_title(self):
        for cls in [
            Money,
            Address,
            LineItem,
            Order,
            PlaceOrder,
            OrderPlaced,
            OrderSummary,
        ]:
            schema = cls.model_json_schema()
            assert schema["title"] == cls.__name__
