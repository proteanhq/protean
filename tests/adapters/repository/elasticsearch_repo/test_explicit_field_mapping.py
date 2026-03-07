"""Tests for explicit Elasticsearch field mapping from entity/aggregate attributes.

Verifies that construct_database_model_class() builds proper ES mappings
for each Protean field type, and that custom @domain.model fields take
precedence over auto-generated mappings.
"""

import pytest
from datetime import datetime

from elasticsearch_dsl import Text

from protean.core.aggregate import BaseAggregate
from protean.core.database_model import BaseDatabaseModel
from protean.core.value_object import BaseValueObject
from protean.fields import (
    Boolean,
    Date,
    DateTime,
    Dict,
    Float,
    Integer,
    List,
    String,
    ValueObject,
    ValueObjectList,
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


class Address(BaseValueObject):
    street: String(max_length=200)
    city: String(max_length=100)


class Tag(BaseValueObject):
    label: String(max_length=50)


class AggregateWithVO(BaseAggregate):
    name: String(max_length=100, required=True)
    address = ValueObject(Address)
    tags = ValueObjectList(content_type=ValueObject(value_object_cls=Tag))


class PartialCustomModel(BaseDatabaseModel):
    """Custom model that only maps 'name', leaving other fields to auto-mapping."""

    name = Text(analyzer="standard")


@pytest.mark.elasticsearch
class TestShadowAndReferenceFieldMapping:
    """Test mapping of ValueObject shadow fields, references, and ValueObjectList"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(AggregateWithVO)
        test_domain.register(Address, part_of=AggregateWithVO)
        test_domain.register(Tag, part_of=AggregateWithVO)
        test_domain.init(traverse=False)

    def test_shadow_fields_mapped_from_value_object(self, test_domain):
        """ValueObject shadow fields (flattened) should be mapped as Keyword"""
        props = _get_mapping_props(test_domain, AggregateWithVO)

        assert props["address_street"]["type"] == "keyword"
        assert props["address_city"]["type"] == "keyword"

    def test_value_object_list_mapped_as_nested(self, test_domain):
        """ValueObjectList fields should be mapped as ES Nested"""
        props = _get_mapping_props(test_domain, AggregateWithVO)

        assert props["tags"]["type"] == "nested"


@pytest.mark.elasticsearch
class TestCustomModelAutoFillsGaps:
    """Test that decorate_database_model_class auto-maps unmapped attributes."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(MappedAggregate)
        test_domain.register_database_model(PartialCustomModel, part_of=MappedAggregate)
        test_domain.init(traverse=False)

    def test_custom_field_preserved(self, test_domain):
        """User-defined Text field should be preserved in the final mapping"""
        model_cls = test_domain.repository_for(MappedAggregate)._database_model
        doc_mapping = model_cls._doc_type.mapping.to_dict()
        props = doc_mapping.get("properties", {})

        assert props["name"]["type"] == "text"

    def test_unmapped_attributes_auto_filled(self, test_domain):
        """Attributes not in the custom model should be auto-mapped"""
        model_cls = test_domain.repository_for(MappedAggregate)._database_model

        # The extra mapping (auto-filled) should include fields not in PartialCustomModel
        idx_mapping = model_cls._index._mapping
        assert idx_mapping is not None
        idx_props = idx_mapping.to_dict().get("properties", {})

        # age, score, is_active, etc. should be auto-mapped
        assert "age" in idx_props
        assert idx_props["age"]["type"] == "integer"
        assert "score" in idx_props
        assert idx_props["score"]["type"] == "float"
        assert "entity_version" in idx_props
        assert idx_props["entity_version"]["type"] == "integer"

    def test_custom_model_keyword_fields_detects_text(self, test_domain):
        """Text fields in custom models should appear in _keyword_fields"""
        model_cls = test_domain.repository_for(MappedAggregate)._database_model

        # 'name' is Text in the custom model → needs .keyword for exact matching
        assert "name" in model_cls._keyword_fields


@pytest.mark.elasticsearch
class TestCustomModelWithSettings:
    """Test decorate_database_model_class with provider-level SETTINGS."""

    @pytest.fixture(autouse=True)
    def register_with_settings(self, test_domain):
        test_domain.config["databases"]["default"]["SETTINGS"] = {"number_of_shards": 3}
        test_domain.register(MappedAggregate)
        test_domain.register_database_model(PartialCustomModel, part_of=MappedAggregate)
        test_domain.init(traverse=False)

    def test_settings_applied_to_decorated_model(self, test_domain):
        """Provider-level SETTINGS should be applied during decoration"""
        model_cls = test_domain.repository_for(MappedAggregate)._database_model

        assert model_cls._index._settings == {"number_of_shards": 3}


@pytest.mark.elasticsearch
class TestAutoIncrementFieldMapping:
    """Test that auto-increment fields are mapped as ES Integer."""

    def test_increment_field_mapped_as_integer(self, test_domain):
        """Fields with increment=True should map to ES Integer"""
        from protean.adapters.repository.elasticsearch import _es_field_mapping_for
        from protean.fields.resolved import ResolvedField

        # Create a mock ResolvedField with increment=True
        field = ResolvedField.__new__(ResolvedField)
        field.identifier = False
        field.increment = True

        es_field = _es_field_mapping_for(field)
        assert es_field.name == "integer"
