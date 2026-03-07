"""Tests for explicit Elasticsearch field mapping from entity/aggregate attributes.

Verifies that construct_database_model_class() builds proper ES mappings
for each Protean field type, and that custom @domain.model fields take
precedence over auto-generated mappings.
"""

import pytest
from datetime import datetime

from protean.core.aggregate import BaseAggregate
from protean.fields import (
    Boolean,
    Date,
    DateTime,
    Dict,
    Float,
    Integer,
    List,
    String,
)


class MappedAggregate(BaseAggregate):
    """Aggregate with diverse field types for mapping tests"""

    name: String(max_length=100, required=True)
    description: String(max_length=500)
    age: Integer()
    score: Float()
    is_active: Boolean(default=True)
    created_at: DateTime(default=datetime.now)
    birth_date: Date()
    tags: List()
    metadata: Dict()


def _get_mapping_props(test_domain, entity_cls) -> dict:
    """Helper to extract field mapping properties as a dict of {name: type_string}"""
    provider = test_domain.providers["default"]
    model_cls = provider.construct_database_model_class(entity_cls)
    mapping_dict = model_cls._index._mapping.to_dict()
    return mapping_dict.get("properties", {})


@pytest.mark.elasticsearch
class TestExplicitFieldMapping:
    """Test that auto-generated models build correct ES mappings"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(MappedAggregate)
        test_domain.init(traverse=False)

    def test_string_fields_mapped_as_keyword(self, test_domain):
        """String fields should be mapped as Keyword for exact matching"""
        props = _get_mapping_props(test_domain, MappedAggregate)

        assert props["name"]["type"] == "keyword"
        assert props["description"]["type"] == "keyword"

    def test_integer_fields_mapped_as_integer(self, test_domain):
        """Integer fields should be mapped as ES Integer"""
        props = _get_mapping_props(test_domain, MappedAggregate)

        assert props["age"]["type"] == "integer"

    def test_float_fields_mapped_as_float(self, test_domain):
        """Float fields should be mapped as ES Float"""
        props = _get_mapping_props(test_domain, MappedAggregate)

        assert props["score"]["type"] == "float"

    def test_boolean_fields_mapped_as_boolean(self, test_domain):
        """Boolean fields should be mapped as ES Boolean"""
        props = _get_mapping_props(test_domain, MappedAggregate)

        assert props["is_active"]["type"] == "boolean"

    def test_datetime_fields_mapped_as_date(self, test_domain):
        """DateTime and Date fields should be mapped as ES Date"""
        props = _get_mapping_props(test_domain, MappedAggregate)

        assert props["created_at"]["type"] == "date"
        assert props["birth_date"]["type"] == "date"

    def test_dict_fields_use_dynamic_mapping(self, test_domain):
        """Dict fields are excluded from explicit mapping (use ES dynamic mapping)"""
        props = _get_mapping_props(test_domain, MappedAggregate)

        assert "metadata" not in props

    def test_list_fields_use_dynamic_mapping(self, test_domain):
        """List fields are excluded from explicit mapping (use ES dynamic mapping)"""
        props = _get_mapping_props(test_domain, MappedAggregate)

        assert "tags" not in props

    def test_identifier_field_mapped_as_keyword(self, test_domain):
        """The ID field should be mapped as Keyword"""
        props = _get_mapping_props(test_domain, MappedAggregate)

        assert props["id"]["type"] == "keyword"

    def test_version_field_mapped_as_integer(self, test_domain):
        """entity_version should be mapped as ES Integer"""
        props = _get_mapping_props(test_domain, MappedAggregate)

        assert props["entity_version"]["type"] == "integer"

    def test_version_field_not_in_mapping_as_underscore(self, test_domain):
        """_version should NOT appear in the mapping (conflicts with ES internal)"""
        props = _get_mapping_props(test_domain, MappedAggregate)

        assert "_version" not in props

    def test_all_mappable_attributes_have_mappings(self, test_domain):
        """Every entity attribute (except _version, List, Dict) should have an explicit mapping"""
        props = _get_mapping_props(test_domain, MappedAggregate)

        expected_fields = {
            "id",
            "name",
            "description",
            "age",
            "score",
            "is_active",
            "created_at",
            "birth_date",
            "entity_version",
        }
        assert set(props.keys()) == expected_fields
