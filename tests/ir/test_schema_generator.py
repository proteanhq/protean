"""Tests for the JSON Schema generator (``protean.ir.generators.schema``)."""

from __future__ import annotations

import json

import pytest

from protean.ir.builder import IRBuilder
from protean.ir.generators.schema import (
    generate_element_schema,
    generate_schemas,
)

from .elements import (
    build_cluster_test_domain,
    build_command_event_test_domain,
    build_extended_field_test_domain,
    build_field_test_domain,
    build_integration_domain,
    build_published_event_domain,
    build_status_field_domain,
    build_via_and_min_length_domain,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ir_for(builder_fn):
    """Build the IR dict from a domain builder function."""
    domain = builder_fn()
    return IRBuilder(domain).build()


def _find_element(ir: dict, name: str) -> dict:
    """Find a data-carrying element by short name in the IR clusters."""
    for cluster in ir.get("clusters", {}).values():
        agg = cluster.get("aggregate", {})
        if agg.get("name") == name:
            return agg
        for section in ("entities", "value_objects", "commands", "events"):
            for fqn, elem in cluster.get(section, {}).items():
                if elem.get("name") == name:
                    return elem
    for fqn, proj in ir.get("projections", {}).items():
        if proj.get("name") == name:
            return proj
    raise KeyError(f"Element {name!r} not found in IR")


# ---------------------------------------------------------------------------
# Basic schema structure
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestSchemaEnvelope:
    """Verify the top-level JSON Schema envelope."""

    @pytest.fixture(autouse=True)
    def setup(self):
        ir = _ir_for(build_cluster_test_domain)
        element = _find_element(ir, "Order")
        self.schema = generate_element_schema(element)

    def test_schema_dialect(self):
        assert (
            self.schema["$schema"]
            == "https://json-schema.org/draft/2020-12/schema"
        )

    def test_type_is_object(self):
        assert self.schema["type"] == "object"

    def test_has_properties(self):
        assert "properties" in self.schema

    def test_has_title(self):
        assert self.schema["title"] == "Order"

    def test_has_description(self):
        assert self.schema["description"] == "An order aggregate with invariants."

    def test_has_required(self):
        assert "required" in self.schema
        assert isinstance(self.schema["required"], list)

    def test_keys_sorted(self):
        keys = list(self.schema.keys())
        assert keys == sorted(keys)

    def test_is_valid_json(self):
        """Schema must be JSON-serializable and deterministic."""
        json_str = json.dumps(self.schema, sort_keys=True)
        roundtrip = json.loads(json_str)
        assert roundtrip == self.schema


# ---------------------------------------------------------------------------
# Standard field type mappings
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestStandardFieldMappings:
    """Verify each IR type maps to the correct JSON Schema type."""

    @pytest.fixture(autouse=True)
    def setup(self):
        ir = _ir_for(build_field_test_domain)
        flat = {}
        for cluster in ir.get("clusters", {}).values():
            agg = cluster.get("aggregate", {})
            if agg.get("fqn"):
                flat[agg["fqn"]] = agg
            for section in ("entities", "value_objects"):
                for fqn, elem in cluster.get(section, {}).items():
                    flat[fqn] = elem

        element = _find_element(ir, "Product")
        self.schema = generate_element_schema(element, all_elements=flat)
        self.props = self.schema["properties"]

    def test_string_field(self):
        p = self.props["name"]
        assert p["type"] == "string"
        assert p["maxLength"] == 200

    def test_text_field(self):
        p = self.props["description"]
        # Text is optional → anyOf
        assert "anyOf" in p
        inner = p["anyOf"][0]
        assert inner["type"] == "string"

    def test_integer_field(self):
        p = self.props["quantity"]
        assert "anyOf" in p
        inner = p["anyOf"][0]
        assert inner["type"] == "integer"
        assert inner["minimum"] == 0

    def test_float_field(self):
        p = self.props["price"]
        assert "anyOf" in p
        inner = p["anyOf"][0]
        assert inner["type"] == "number"
        assert inner["minimum"] == 0.0

    def test_boolean_field(self):
        p = self.props["is_active"]
        # Boolean with default → optional
        assert "anyOf" in p
        inner = p["anyOf"][0]
        assert inner["type"] == "boolean"

    def test_date_field(self):
        p = self.props["launch_date"]
        assert "anyOf" in p
        inner = p["anyOf"][0]
        assert inner["format"] == "date"
        assert inner["type"] == "string"

    def test_datetime_field(self):
        p = self.props["created_at"]
        assert "anyOf" in p
        inner = p["anyOf"][0]
        assert inner["format"] == "date-time"
        assert inner["type"] == "string"

    def test_auto_field(self):
        p = self.props["id"]
        assert p["type"] == "string"

    def test_identifier_field(self):
        p = self.props["sku"]
        assert p["type"] == "string"


# ---------------------------------------------------------------------------
# Container fields
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestContainerFields:
    """Verify List and Dict field schema generation."""

    @pytest.fixture(autouse=True)
    def setup(self):
        ir = _ir_for(build_field_test_domain)
        element = _find_element(ir, "Product")
        self.schema = generate_element_schema(element)
        self.props = self.schema["properties"]

    def test_list_field_with_content_type(self):
        p = self.props["tags"]
        assert "anyOf" in p
        inner = p["anyOf"][0]
        assert inner["type"] == "array"
        assert inner["items"] == {"type": "string"}

    def test_dict_field(self):
        p = self.props["metadata_field"]
        assert "anyOf" in p
        inner = p["anyOf"][0]
        assert inner["type"] == "object"


# ---------------------------------------------------------------------------
# Value object and entity references ($defs and $ref)
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestRefAndDefs:
    """Verify ``$ref`` and ``$defs`` for value objects and entities."""

    @pytest.fixture(autouse=True)
    def setup(self):
        ir = _ir_for(build_cluster_test_domain)
        flat = {}
        for cluster in ir.get("clusters", {}).values():
            agg = cluster.get("aggregate", {})
            if agg.get("fqn"):
                flat[agg["fqn"]] = agg
            for section in ("entities", "value_objects"):
                for fqn, elem in cluster.get(section, {}).items():
                    flat[fqn] = elem

        element = _find_element(ir, "Order")
        self.schema = generate_element_schema(element, all_elements=flat)

    def test_value_object_ref(self):
        p = self.schema["properties"]["shipping_address"]
        # Optional VO field is wrapped in anyOf with null
        assert "anyOf" in p
        ref_schema = p["anyOf"][0]
        assert ref_schema["$ref"] == "#/$defs/ShippingAddress"
        assert p["anyOf"][1] == {"type": "null"}

    def test_has_many_ref(self):
        p = self.schema["properties"]["items"]
        # has_many is optional, so wrapped in anyOf
        assert "anyOf" in p
        array_schema = p["anyOf"][0]
        assert array_schema["type"] == "array"
        assert array_schema["items"]["$ref"] == "#/$defs/LineItem"

    def test_defs_present(self):
        assert "$defs" in self.schema

    def test_defs_shipping_address(self):
        defs = self.schema["$defs"]
        assert "ShippingAddress" in defs
        sa = defs["ShippingAddress"]
        assert sa["type"] == "object"
        assert "street" in sa["properties"]
        assert "city" in sa["properties"]

    def test_defs_line_item(self):
        defs = self.schema["$defs"]
        assert "LineItem" in defs
        li = defs["LineItem"]
        assert li["type"] == "object"
        assert "product_name" in li["properties"]
        assert "quantity" in li["properties"]

    def test_defs_keys_sorted(self):
        defs = self.schema["$defs"]
        assert list(defs.keys()) == sorted(defs.keys())


# ---------------------------------------------------------------------------
# Has-one reference
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestHasOneRef:
    """Verify ``has_one`` generates a ``$ref``."""

    def test_has_one_produces_ref(self):
        ir = _ir_for(build_extended_field_test_domain)
        flat = {}
        for cluster in ir.get("clusters", {}).values():
            agg = cluster.get("aggregate", {})
            if agg.get("fqn"):
                flat[agg["fqn"]] = agg
            for section in ("entities", "value_objects"):
                for fqn, elem in cluster.get(section, {}).items():
                    flat[fqn] = elem

        element = _find_element(ir, "Catalog")
        schema = generate_element_schema(element, all_elements=flat)

        # HasOne is optional, so wrapped in anyOf with null
        p = schema["properties"]["featured"]
        assert "anyOf" in p
        assert p["anyOf"][0]["$ref"] == "#/$defs/FeaturedItem"
        assert p["anyOf"][1] == {"type": "null"}


# ---------------------------------------------------------------------------
# Optional fields (anyOf with null)
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestOptionalFields:
    """Verify optional (non-required) fields use ``anyOf`` with null."""

    @pytest.fixture(autouse=True)
    def setup(self):
        ir = _ir_for(build_cluster_test_domain)
        element = _find_element(ir, "Order")
        self.schema = generate_element_schema(element)
        self.props = self.schema["properties"]

    def test_optional_float_uses_anyof(self):
        p = self.props["total"]
        assert "anyOf" in p
        types = [s.get("type") for s in p["anyOf"]]
        assert "number" in types
        assert "null" in types

    def test_required_string_no_anyof(self):
        p = self.props["customer_name"]
        assert "anyOf" not in p
        assert p["type"] == "string"

    def test_identifier_no_anyof(self):
        p = self.props["id"]
        assert "anyOf" not in p


# ---------------------------------------------------------------------------
# Required list
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestRequiredList:
    """Verify the ``required`` array is correct and sorted."""

    def test_required_fields(self):
        ir = _ir_for(build_cluster_test_domain)
        element = _find_element(ir, "Order")
        schema = generate_element_schema(element)
        assert "customer_name" in schema["required"]
        assert "id" in schema["required"]
        assert schema["required"] == sorted(schema["required"])

    def test_optional_fields_not_in_required(self):
        ir = _ir_for(build_cluster_test_domain)
        element = _find_element(ir, "Order")
        schema = generate_element_schema(element)
        assert "total" not in schema["required"]
        assert "shipping_address" not in schema["required"]


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestConstraints:
    """Verify constraints are mapped to JSON Schema keywords."""

    @pytest.fixture(autouse=True)
    def setup(self):
        ir = _ir_for(build_cluster_test_domain)
        flat = {}
        for cluster in ir.get("clusters", {}).values():
            agg = cluster.get("aggregate", {})
            if agg.get("fqn"):
                flat[agg["fqn"]] = agg
            for section in ("entities", "value_objects"):
                for fqn, elem in cluster.get(section, {}).items():
                    flat[fqn] = elem
        self.ir = ir
        self.flat = flat

    def test_max_length(self):
        element = _find_element(self.ir, "Order")
        schema = generate_element_schema(element, all_elements=self.flat)
        p = schema["properties"]["customer_name"]
        assert p["maxLength"] == 100

    def test_min_value(self):
        element = _find_element(self.ir, "Order")
        schema = generate_element_schema(element, all_elements=self.flat)
        p = schema["properties"]["total"]
        inner = p["anyOf"][0]
        assert inner["minimum"] == 0.0

    def test_min_length(self):
        ir = _ir_for(build_via_and_min_length_domain)
        element = _find_element(ir, "Author")
        schema = generate_element_schema(element)
        p = schema["properties"]["name"]
        assert p["minLength"] == 3


# ---------------------------------------------------------------------------
# Status fields with enum
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestStatusFieldSchema:
    """Verify Status fields generate ``enum`` in JSON Schema."""

    @pytest.fixture(autouse=True)
    def setup(self):
        ir = _ir_for(build_status_field_domain)
        element = _find_element(ir, "Order")
        self.schema = generate_element_schema(element)
        self.props = self.schema["properties"]

    def test_status_enum(self):
        p = self.props["status"]
        assert "anyOf" in p
        inner = p["anyOf"][0]
        assert "enum" in inner
        assert "DRAFT" in inner["enum"]
        assert "PLACED" in inner["enum"]

    def test_status_default(self):
        p = self.props["status"]
        assert p["default"] == "DRAFT"


# ---------------------------------------------------------------------------
# x-protean-* extension metadata
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestExtensionMetadata:
    """Verify ``x-protean-*`` extension keys."""

    def test_aggregate_extensions(self):
        ir = _ir_for(build_cluster_test_domain)
        element = _find_element(ir, "Order")
        schema = generate_element_schema(element)
        assert schema["x-protean-element-type"] == "aggregate"
        assert "Order" in schema["x-protean-fqn"]
        assert "x-protean-identity-field" in schema

    def test_command_extensions(self):
        ir = _ir_for(build_command_event_test_domain)
        element = _find_element(ir, "PlaceOrder")
        schema = generate_element_schema(element)
        assert schema["x-protean-element-type"] == "command"
        assert "x-protean-version" in schema
        assert schema["x-protean-version"] == 1
        assert "x-protean-type" in schema
        assert "x-protean-aggregate" in schema

    def test_event_extensions(self):
        ir = _ir_for(build_command_event_test_domain)
        element = _find_element(ir, "OrderPlaced")
        schema = generate_element_schema(element)
        assert schema["x-protean-element-type"] == "event"
        assert schema["x-protean-version"] == 1

    def test_fact_event_extension(self):
        ir = _ir_for(build_command_event_test_domain)
        element = _find_element(ir, "OrderFactEvent")
        schema = generate_element_schema(element)
        assert schema.get("x-protean-is-fact-event") is True
        assert schema.get("x-protean-auto-generated") is True

    def test_value_object_extensions(self):
        ir = _ir_for(build_cluster_test_domain)
        element = _find_element(ir, "ShippingAddress")
        schema = generate_element_schema(element)
        assert schema["x-protean-element-type"] == "value_object"


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestDefaultValues:
    """Verify default values appear in the schema."""

    def test_literal_default(self):
        ir = _ir_for(build_field_test_domain)
        element = _find_element(ir, "Product")
        schema = generate_element_schema(element)
        p = schema["properties"]["is_active"]
        assert p["default"] is True

    def test_numeric_default(self):
        ir = _ir_for(build_field_test_domain)
        element = _find_element(ir, "Product")
        schema = generate_element_schema(element)
        p = schema["properties"]["score"]
        assert p["default"] == 0.0

    def test_callable_default_omitted(self):
        """Callable defaults should not appear in JSON Schema."""
        ir = _ir_for(build_extended_field_test_domain)
        element = _find_element(ir, "Catalog")
        schema = generate_element_schema(element)
        p = schema["properties"]["items_cache"]
        assert "default" not in p


# ---------------------------------------------------------------------------
# Field descriptions
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestFieldDescriptions:
    """Verify field-level descriptions in the schema."""

    def test_description_present(self):
        ir = _ir_for(build_extended_field_test_domain)
        element = _find_element(ir, "Catalog")
        schema = generate_element_schema(element)
        p = schema["properties"]["name"]
        assert p.get("description") == "Catalog name"

    def test_description_absent_when_not_set(self):
        ir = _ir_for(build_extended_field_test_domain)
        element = _find_element(ir, "Catalog")
        schema = generate_element_schema(element)
        p = schema["properties"]["items_cache"]
        assert "description" not in p


# ---------------------------------------------------------------------------
# Reference fields
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestReferenceFields:
    """Verify reference fields map to string type."""

    def test_reference_is_string(self):
        ir = _ir_for(build_cluster_test_domain)
        # LineItem entity has an auto-generated reference to Order
        element = _find_element(ir, "LineItem")
        schema = generate_element_schema(element)
        # Reference field should be string (FK value)
        ref_field = schema["properties"].get("order")
        if ref_field:
            # It may be anyOf with null for optional ref
            if "anyOf" in ref_field:
                types = [s.get("type") for s in ref_field["anyOf"]]
                assert "string" in types
            else:
                assert ref_field["type"] == "string"


# ---------------------------------------------------------------------------
# generate_schemas — full IR processing
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestGenerateSchemas:
    """Verify ``generate_schemas()`` processes a full IR dict."""

    @pytest.fixture(autouse=True)
    def setup(self):
        ir = _ir_for(build_cluster_test_domain)
        self.schemas = generate_schemas(ir)

    def test_returns_dict(self):
        assert isinstance(self.schemas, dict)

    def test_includes_aggregate(self):
        found = any("Order" in fqn for fqn in self.schemas if "Memory" not in fqn)
        assert found, f"Order aggregate not found in schemas: {list(self.schemas.keys())}"

    def test_includes_entity(self):
        found = any("LineItem" in fqn for fqn in self.schemas)
        assert found, f"LineItem entity not found in schemas: {list(self.schemas.keys())}"

    def test_includes_value_object(self):
        found = any("ShippingAddress" in fqn for fqn in self.schemas)
        assert found

    def test_fqns_sorted(self):
        keys = list(self.schemas.keys())
        assert keys == sorted(keys)

    def test_each_schema_has_dialect(self):
        for fqn, schema in self.schemas.items():
            assert "$schema" in schema, f"Missing $schema in {fqn}"

    def test_does_not_include_handlers(self):
        """Handlers and services should not appear in schemas."""
        for fqn in self.schemas:
            schema = self.schemas[fqn]
            elem_type = schema.get("x-protean-element-type", "")
            assert elem_type in (
                "aggregate",
                "entity",
                "value_object",
                "command",
                "event",
                "projection",
            ), f"Unexpected element type {elem_type!r} for {fqn}"


@pytest.mark.no_test_domain
class TestGenerateSchemasWithCommandsEvents:
    """Verify commands and events are included in ``generate_schemas``."""

    @pytest.fixture(autouse=True)
    def setup(self):
        ir = _ir_for(build_command_event_test_domain)
        self.schemas = generate_schemas(ir)

    def test_includes_commands(self):
        found = any("PlaceOrder" in fqn for fqn in self.schemas)
        assert found

    def test_includes_events(self):
        found = any("OrderPlaced" in fqn for fqn in self.schemas)
        assert found


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestDeterminism:
    """Verify the same IR produces the same schema."""

    def test_same_ir_same_schema(self):
        ir1 = _ir_for(build_cluster_test_domain)
        ir2 = _ir_for(build_cluster_test_domain)
        schemas1 = generate_schemas(ir1)
        schemas2 = generate_schemas(ir2)
        assert json.dumps(schemas1, sort_keys=True) == json.dumps(
            schemas2, sort_keys=True
        )

    def test_single_element_deterministic(self):
        ir = _ir_for(build_cluster_test_domain)
        element = _find_element(ir, "Order")
        s1 = generate_element_schema(element)
        s2 = generate_element_schema(element)
        assert s1 == s2


# ---------------------------------------------------------------------------
# Integration: rich domain with projections
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestIntegrationDomain:
    """Test schema generation against the rich integration domain."""

    @pytest.fixture(autouse=True)
    def setup(self):
        ir = _ir_for(build_integration_domain)
        self.schemas = generate_schemas(ir)
        self.ir = ir

    def test_projection_included(self):
        found = any("OrderDashboard" in fqn for fqn in self.schemas)
        assert found

    def test_projection_extensions(self):
        for fqn, schema in self.schemas.items():
            if "OrderDashboard" in fqn:
                assert schema["x-protean-element-type"] == "projection"
                break

    def test_nested_vo_in_entity(self):
        """LineItem has a Money value object — verify $defs resolution."""
        flat = {}
        for cluster in self.ir.get("clusters", {}).values():
            agg = cluster.get("aggregate", {})
            if agg.get("fqn"):
                flat[agg["fqn"]] = agg
            for section in ("entities", "value_objects"):
                for fqn, elem in cluster.get(section, {}).items():
                    flat[fqn] = elem

        element = _find_element(self.ir, "LineItem")
        schema = generate_element_schema(element, all_elements=flat)
        assert "$defs" in schema
        assert "Money" in schema["$defs"]

    def test_all_schemas_json_serializable(self):
        for fqn, schema in self.schemas.items():
            json_str = json.dumps(schema)
            assert json.loads(json_str) == schema


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_element_without_fields(self):
        """An element with no fields should produce a minimal schema."""
        element = {"element_type": "AGGREGATE", "name": "Empty", "fqn": "app.Empty"}
        schema = generate_element_schema(element)
        assert schema["type"] == "object"
        assert schema["properties"] == {}
        assert "required" not in schema

    def test_element_without_name(self):
        """An element without a name should not have a title."""
        element = {"fields": {}, "fqn": "app.Anon", "element_type": "COMMAND"}
        schema = generate_element_schema(element)
        assert "title" not in schema

    def test_no_defs_when_no_refs(self):
        """Schema should not have ``$defs`` when there are no references."""
        ir = _ir_for(build_command_event_test_domain)
        element = _find_element(ir, "PlaceOrder")
        schema = generate_element_schema(element)
        assert "$defs" not in schema

    def test_ref_without_all_elements(self):
        """Without ``all_elements``, refs produce minimal object defs."""
        ir = _ir_for(build_cluster_test_domain)
        element = _find_element(ir, "Order")
        schema = generate_element_schema(element, all_elements=None)
        # $defs should exist but with minimal object schemas
        if "$defs" in schema:
            for def_schema in schema["$defs"].values():
                assert def_schema == {"type": "object"}

    def test_list_without_mapped_content_type(self):
        """List field with unmapped content_type produces array without items."""
        from protean.ir.generators.schema import _field_to_schema

        field = {"kind": "list", "type": "List", "content_type": "UnknownType"}
        schema = _field_to_schema(field)
        assert schema["type"] == "array"
        assert "items" not in schema

    def test_list_without_content_type(self):
        """List field with no content_type produces bare array."""
        from protean.ir.generators.schema import _field_to_schema

        field = {"kind": "list", "type": "List"}
        schema = _field_to_schema(field)
        assert schema == {"type": "array"}

    def test_value_object_list_produces_array_with_ref(self):
        """value_object_list kind produces array with $ref items."""
        from protean.ir.generators.schema import _field_to_schema

        field = {"kind": "value_object_list", "target": "app.Money"}
        schema = _field_to_schema(field)
        assert schema["type"] == "array"
        assert schema["items"]["$ref"] == "#/$defs/Money"

    def test_max_value_constraint(self):
        """max_value maps to JSON Schema maximum."""
        from protean.ir.generators.schema import _field_to_schema

        field = {"kind": "standard", "type": "Integer", "max_value": 100}
        schema = _field_to_schema(field)
        assert schema["maximum"] == 100

    def test_published_event_extension(self):
        """Published events get x-protean-published."""
        ir = _ir_for(build_published_event_domain)
        element = _find_element(ir, "AccountCreated")
        schema = generate_element_schema(element)
        assert schema.get("x-protean-published") is True

    def test_event_sourced_aggregate_extension(self):
        """Event-sourced aggregate gets x-protean-is-event-sourced."""
        from .elements import build_es_aggregate_domain

        ir = _ir_for(build_es_aggregate_domain)
        element = _find_element(ir, "BankAccount")
        schema = generate_element_schema(element)
        assert schema.get("x-protean-is-event-sourced") is True

    def test_auto_increment_maps_to_integer(self):
        """Auto field with increment=True should map to integer."""
        from protean.ir.generators.schema import _field_to_schema

        field = {"kind": "auto", "type": "Auto", "increment": True}
        schema = _field_to_schema(field)
        assert schema == {"type": "integer"}

    def test_auto_without_increment_maps_to_string(self):
        """Auto field without increment should map to string."""
        from protean.ir.generators.schema import _field_to_schema

        field = {"kind": "auto", "type": "Auto"}
        schema = _field_to_schema(field)
        assert schema == {"type": "string"}

    def test_cyclic_reference_does_not_recurse(self):
        """Cyclic references should not cause infinite recursion."""
        from protean.ir.generators.schema import _collect_defs

        all_elements = {
            "app.A": {
                "fields": {
                    "b": {"kind": "value_object", "target": "app.B"},
                },
            },
            "app.B": {
                "fields": {
                    "a": {"kind": "has_one", "target": "app.A"},
                },
            },
        }
        # Should complete without RecursionError
        defs = _collect_defs(all_elements["app.A"]["fields"], all_elements)
        assert "B" in defs
        assert "A" in defs
