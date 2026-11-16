"""Generic native JSON storage tests for providers with NATIVE_JSON capability.

Covers native JSON persistence, nested structures, and null handling.
These tests only run against providers that declare NATIVE_JSON
in their capabilities (e.g., PostgreSQL). Memory and SQLite store
JSON as serialized text.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import Dict, String


class JsonDocument(BaseAggregate):
    name: String(max_length=100, required=True)
    data: Dict()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(JsonDocument)
    test_domain.init(traverse=False)


@pytest.mark.native_json
class TestNativeJsonStorage:
    """Persist aggregates with JSON data and verify structure is preserved."""

    def test_persist_flat_json(self, test_domain):
        doc = JsonDocument(
            name="flat",
            data={"key": "value", "count": 42, "active": True},
        )
        test_domain.repository_for(JsonDocument).add(doc)

        retrieved = test_domain.repository_for(JsonDocument).get(doc.id)
        assert retrieved.data == {"key": "value", "count": 42, "active": True}

    def test_persist_nested_json(self, test_domain):
        nested_data = {
            "level1": {
                "level2": {"level3": "deep_value"},
                "sibling": [1, 2, 3],
            },
            "top_list": [{"a": 1}, {"b": 2}],
        }
        doc = JsonDocument(name="nested", data=nested_data)
        test_domain.repository_for(JsonDocument).add(doc)

        retrieved = test_domain.repository_for(JsonDocument).get(doc.id)
        assert retrieved.data == nested_data
        assert retrieved.data["level1"]["level2"]["level3"] == "deep_value"
        assert retrieved.data["level1"]["sibling"] == [1, 2, 3]
        assert retrieved.data["top_list"][0] == {"a": 1}

    def test_persist_json_with_empty_dict(self, test_domain):
        doc = JsonDocument(name="empty", data={})
        test_domain.repository_for(JsonDocument).add(doc)

        retrieved = test_domain.repository_for(JsonDocument).get(doc.id)
        assert retrieved.data == {}


@pytest.mark.native_json
class TestNativeJsonNulls:
    """Verify null/None handling in native JSON fields."""

    def test_persist_default_json_field(self, test_domain):
        doc = JsonDocument(name="default-data")
        test_domain.repository_for(JsonDocument).add(doc)

        retrieved = test_domain.repository_for(JsonDocument).get(doc.id)
        # Dict fields default to empty dict when not provided
        assert retrieved.data == {}

    def test_persist_json_with_null_values(self, test_domain):
        doc = JsonDocument(
            name="null-values",
            data={"present": "yes", "absent": None},
        )
        test_domain.repository_for(JsonDocument).add(doc)

        retrieved = test_domain.repository_for(JsonDocument).get(doc.id)
        assert retrieved.data["present"] == "yes"
        assert retrieved.data["absent"] is None
