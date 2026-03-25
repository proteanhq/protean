"""Meta-schema validation and advanced edge case tests for JSON Schema generation.

Every generated schema is validated against JSON Schema Draft 2020-12
meta-schema to ensure standards compliance.  Additional edge case tests
cover empty aggregates, deeply nested structures, combined constraints,
status transitions, callable defaults, event-sourced aggregates, and
fact events.
"""

from __future__ import annotations

import json

import jsonschema
import pytest

from protean.ir.builder import IRBuilder
from protean.ir.generators.schema import generate_element_schema, generate_schemas

from .elements import (
    build_cluster_test_domain,
    build_command_event_test_domain,
    build_es_aggregate_domain,
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

_META_SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"


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


def _validate_against_meta_schema(schema: dict) -> None:
    """Validate a schema dict against JSON Schema Draft 2020-12 meta-schema."""
    validator_cls = jsonschema.validators.validator_for({"$schema": _META_SCHEMA_URI})
    validator_cls.check_schema(schema)


# ---------------------------------------------------------------------------
# Meta-schema validation: every domain builder
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestMetaSchemaValidation:
    """All generated schemas must validate against the Draft 2020-12 meta-schema."""

    @pytest.mark.parametrize(
        "builder_fn",
        [
            build_cluster_test_domain,
            build_command_event_test_domain,
            build_field_test_domain,
            build_extended_field_test_domain,
            build_via_and_min_length_domain,
            build_status_field_domain,
            build_es_aggregate_domain,
            build_published_event_domain,
            build_integration_domain,
        ],
        ids=lambda fn: fn.__name__,
    )
    def test_all_schemas_pass_meta_schema(self, builder_fn):
        ir = _ir_for(builder_fn)
        schemas = generate_schemas(ir)
        assert schemas, f"No schemas generated for {builder_fn.__name__}"
        for fqn, schema in schemas.items():
            _validate_against_meta_schema(schema)

    def test_empty_element_passes_meta_schema(self):
        """An element with no fields validates against meta-schema."""
        element = {
            "element_type": "AGGREGATE",
            "name": "Empty",
            "fqn": "app.Empty",
            "fields": {},
        }
        schema = generate_element_schema(element)
        _validate_against_meta_schema(schema)

    def test_element_without_name_passes_meta_schema(self):
        element = {"fields": {}, "fqn": "app.Anon", "element_type": "COMMAND"}
        schema = generate_element_schema(element)
        _validate_against_meta_schema(schema)


# ---------------------------------------------------------------------------
# Edge case: empty aggregate (only auto id field)
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestEmptyAggregate:
    """Aggregate with no user-defined fields (only auto-generated id)."""

    def test_empty_aggregate_schema(self):
        from protean import Domain

        domain = Domain(name="EmptyTest", root_path=".")

        @domain.aggregate
        class Marker:
            pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        schemas = generate_schemas(ir)

        marker_schemas = {fqn: s for fqn, s in schemas.items() if "Marker" in fqn}
        assert len(marker_schemas) == 1

        schema = next(iter(marker_schemas.values()))
        assert schema["type"] == "object"
        assert "id" in schema["properties"]
        _validate_against_meta_schema(schema)


# ---------------------------------------------------------------------------
# Edge case: deeply nested structures (aggregate → entity → VO)
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestDeeplyNested:
    """Aggregate containing entity that contains a value object."""

    def test_three_level_nesting(self):
        ir = _ir_for(build_integration_domain)
        flat = {}
        for cluster in ir.get("clusters", {}).values():
            agg = cluster.get("aggregate", {})
            if agg.get("fqn"):
                flat[agg["fqn"]] = agg
            for section in ("entities", "value_objects"):
                for fqn, elem in cluster.get(section, {}).items():
                    flat[fqn] = elem

        # Order → LineItem (entity) → Money (VO)
        element = _find_element(ir, "Order")
        schema = generate_element_schema(element, all_elements=flat)

        assert "$defs" in schema
        assert "LineItem" in schema["$defs"]

        # Money should also be in $defs (from nested resolution)
        assert "Money" in schema["$defs"]

        _validate_against_meta_schema(schema)


# ---------------------------------------------------------------------------
# Edge case: all constraint types combined
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCombinedConstraints:
    """Field with multiple constraint types set simultaneously."""

    def test_integer_all_constraints(self):
        from protean.ir.generators.schema import _field_to_schema

        field = {
            "kind": "standard",
            "type": "Integer",
            "max_value": 100,
            "min_value": 1,
            "required": True,
            "unique": True,
        }
        schema = _field_to_schema(field)
        assert schema["type"] == "integer"
        assert schema["minimum"] == 1
        assert schema["maximum"] == 100

    def test_string_all_constraints(self):
        from protean.ir.generators.schema import _field_to_schema

        field = {
            "kind": "standard",
            "type": "String",
            "max_length": 50,
            "min_length": 3,
            "choices": ["A", "B", "C"],
        }
        schema = _field_to_schema(field)
        assert schema["type"] == "string"
        assert schema["maxLength"] == 50
        assert schema["minLength"] == 3
        assert schema["enum"] == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# Edge case: status fields with transition maps
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestStatusWithTransitions:
    """Status fields with transition maps produce correct enum."""

    def test_status_enum_values(self):
        ir = _ir_for(build_status_field_domain)
        schemas = generate_schemas(ir)

        order_schemas = {fqn: s for fqn, s in schemas.items() if "Order" in fqn}
        assert order_schemas

        schema = next(iter(order_schemas.values()))
        status_prop = schema["properties"]["status"]
        inner = status_prop["anyOf"][0] if "anyOf" in status_prop else status_prop
        assert "enum" in inner
        assert set(inner["enum"]) >= {
            "DRAFT",
            "PLACED",
            "CONFIRMED",
            "SHIPPED",
            "CANCELLED",
        }

        _validate_against_meta_schema(schema)


# ---------------------------------------------------------------------------
# Edge case: callable defaults
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCallableDefaults:
    """Callable defaults must not leak into JSON Schema."""

    def test_callable_default_not_in_schema(self):
        ir = _ir_for(build_extended_field_test_domain)
        element = _find_element(ir, "Catalog")
        schema = generate_element_schema(element)

        items_cache = schema["properties"]["items_cache"]
        # Ensure <callable> doesn't appear anywhere in the property
        serialized = json.dumps(items_cache)
        assert "<callable>" not in serialized


# ---------------------------------------------------------------------------
# Edge case: event-sourced aggregates
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestEventSourcedAggregate:
    """Event-sourced aggregates carry correct extension metadata."""

    def test_is_event_sourced_extension(self):
        ir = _ir_for(build_es_aggregate_domain)
        schemas = generate_schemas(ir)

        ba_schemas = {fqn: s for fqn, s in schemas.items() if "BankAccount" in fqn}
        assert ba_schemas

        schema = next(iter(ba_schemas.values()))
        assert schema.get("x-protean-is-event-sourced") is True
        _validate_against_meta_schema(schema)


# ---------------------------------------------------------------------------
# Edge case: fact events (auto-generated)
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestFactEvents:
    """Fact events carry auto-generated and is-fact-event metadata."""

    def test_fact_event_metadata(self):
        ir = _ir_for(build_command_event_test_domain)
        schemas = generate_schemas(ir)

        fact_schemas = {
            fqn: s
            for fqn, s in schemas.items()
            if s.get("x-protean-is-fact-event") is True
        }
        assert fact_schemas, "No fact events found in schemas"

        for fqn, schema in fact_schemas.items():
            assert schema.get("x-protean-auto-generated") is True
            _validate_against_meta_schema(schema)


# ---------------------------------------------------------------------------
# End-to-end: realistic domain → generate schemas → validate → payload
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestEndToEndPayloadValidation:
    """Generate schemas from the integration domain and validate sample payloads."""

    @pytest.fixture(autouse=True)
    def setup(self):
        ir = _ir_for(build_integration_domain)
        self.schemas = generate_schemas(ir)

    def test_all_schemas_valid_against_meta_schema(self):
        for fqn, schema in self.schemas.items():
            _validate_against_meta_schema(schema)

    def test_valid_command_payload(self):
        """A valid PlaceOrder payload passes validation."""
        schema = next(s for fqn, s in self.schemas.items() if "PlaceOrder" in fqn)
        jsonschema.validate({"customer_name": "Alice"}, schema)

    def test_invalid_command_payload_missing_required(self):
        """PlaceOrder payload missing required field fails validation."""
        schema = next(s for fqn, s in self.schemas.items() if "PlaceOrder" in fqn)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({}, schema)

    def test_valid_event_payload(self):
        """A valid OrderPlaced payload passes validation."""
        schema = next(s for fqn, s in self.schemas.items() if "OrderPlaced" in fqn)
        payload = {
            "order_id": "order-123",
            "customer_name": "Alice",
            "total": 99.99,
        }
        jsonschema.validate(payload, schema)

    def test_invalid_event_payload_wrong_type(self):
        """OrderPlaced payload with wrong type fails validation."""
        schema = next(s for fqn, s in self.schemas.items() if "OrderPlaced" in fqn)
        payload = {
            "order_id": "order-123",
            "customer_name": "Alice",
            "total": "not-a-number",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(payload, schema)

    def test_all_schemas_json_serializable_and_deterministic(self):
        for fqn, schema in self.schemas.items():
            json_str = json.dumps(schema, sort_keys=True)
            roundtrip = json.loads(json_str)
            assert roundtrip == schema
