"""The examples on the schema generation guide behave as the page says."""

import json

import jsonschema
import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def example(tmp_path, monkeypatch):
    # The example writes its schemas under .protean/ in the working directory.
    monkeypatch.chdir(tmp_path)
    return load_example("guides/compose-a-domain/schema-generation/001.py")


def _read(tmp_path, path):
    return json.loads((tmp_path / ".protean/schemas" / path).read_text())


def test_schemas_are_grouped_by_aggregate_cluster(example, tmp_path):
    written = sorted(
        path.relative_to(tmp_path / ".protean/schemas").as_posix()
        for path in (tmp_path / ".protean/schemas").rglob("*.json")
    )

    assert written == [
        "Order/aggregates/Order.v1.json",
        "Order/events/OrderPlaced.v1.json",
        "Order/value_objects/ShippingAddress.v1.json",
    ]


def test_event_schema_has_the_shape_the_page_shows(example, tmp_path):
    schema = _read(tmp_path, "Order/events/OrderPlaced.v1.json")

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "OrderPlaced"
    assert schema["type"] == "object"
    assert schema["properties"] == {
        "order_id": {"type": "string", "minLength": 1},
        "customer_name": {"type": "string", "maxLength": 255, "minLength": 1},
        "total": {"type": "number"},
    }
    assert schema["required"] == ["customer_name", "order_id", "total"]
    assert schema["x-protean-element-type"] == "event"
    assert schema["x-protean-fqn"] == f"{example.__name__}.OrderPlaced"
    assert schema["x-protean-aggregate"] == f"{example.__name__}.Order"
    assert schema["x-protean-version"] == 1
    assert schema["x-protean-type"] == "Ordering.OrderPlaced.v1"


def test_value_object_is_a_def_with_a_ref(example, tmp_path):
    schema = _read(tmp_path, "Order/aggregates/Order.v1.json")

    assert schema["properties"]["shipping_address"] == {
        "$ref": "#/$defs/ShippingAddress"
    }
    assert schema["$defs"]["ShippingAddress"] == {
        "type": "object",
        "properties": {
            "street": {"type": "string", "maxLength": 255, "minLength": 1},
            "city": {"type": "string", "maxLength": 100, "minLength": 1},
        },
        "required": ["city", "street"],
    }


def test_optional_field_allows_null(example, tmp_path):
    schema = _read(tmp_path, "Order/aggregates/Order.v1.json")

    assert schema["properties"]["total"] == {
        "anyOf": [{"type": "number", "minimum": 0.0}, {"type": "null"}]
    }


def test_payload_passes_the_generated_schema(example):
    # The example raises if validation fails; check its inputs are the page's.
    assert example.payload == {
        "order_id": "order-123",
        "customer_name": "Alice",
        "total": 99.99,
    }
    jsonschema.validate(example.payload, example.schema)


def test_payload_without_a_total_is_rejected(example):
    payload = {"order_id": "order-123", "customer_name": "Alice"}

    with pytest.raises(jsonschema.ValidationError, match="'total' is a required"):
        jsonschema.validate(payload, example.schema)
