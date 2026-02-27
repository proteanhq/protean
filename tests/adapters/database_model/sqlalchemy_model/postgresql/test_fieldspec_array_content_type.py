"""Tests for FieldSpec-based content_type resolution in PostgreSQL ARRAY columns.

When a List field uses a FieldSpec as content_type (e.g. ``List(content_type=Dict())``,
``List(content_type=String())``, ``List(content_type=Integer())``), the SQLAlchemy
adapter must resolve the FieldSpec's python_type to the correct SA column type.
This includes unwrapping Union types like ``dict | list`` from ``Dict()``.
"""

import pytest
from sqlalchemy import types as sa_types
from sqlalchemy.dialects import postgresql as psql

from protean.core.aggregate import BaseAggregate
from protean.fields import Dict, Float, Integer, List, String
from protean.utils.globals import current_domain


class DictListAggregate(BaseAggregate):
    label = String(max_length=50)
    payloads = List(content_type=Dict())


class StringListAggregate(BaseAggregate):
    label = String(max_length=50)
    tags = List(content_type=String())


class IntListAggregate(BaseAggregate):
    label = String(max_length=50)
    scores = List(content_type=Integer())


class FloatListAggregate(BaseAggregate):
    label = String(max_length=50)
    weights = List(content_type=Float())


@pytest.mark.postgresql
class TestFieldSpecArrayColumnType:
    """Verify that FieldSpec content_type produces the correct SA ARRAY item type."""

    def test_list_of_dict_maps_to_json_array(self, test_domain):
        test_domain.register(DictListAggregate)

        model_cls = test_domain.repository_for(DictListAggregate)._database_model
        col_type = model_cls.payloads.property.columns[0].type

        assert isinstance(col_type, psql.ARRAY)
        assert isinstance(col_type.item_type, sa_types.JSON)

    def test_list_of_string_maps_to_string_array(self, test_domain):
        test_domain.register(StringListAggregate)

        model_cls = test_domain.repository_for(StringListAggregate)._database_model
        col_type = model_cls.tags.property.columns[0].type

        assert isinstance(col_type, psql.ARRAY)
        assert isinstance(col_type.item_type, sa_types.String)

    def test_list_of_integer_maps_to_integer_array(self, test_domain):
        test_domain.register(IntListAggregate)

        model_cls = test_domain.repository_for(IntListAggregate)._database_model
        col_type = model_cls.scores.property.columns[0].type

        assert isinstance(col_type, psql.ARRAY)
        assert isinstance(col_type.item_type, sa_types.Integer)

    def test_list_of_float_maps_to_float_array(self, test_domain):
        test_domain.register(FloatListAggregate)

        model_cls = test_domain.repository_for(FloatListAggregate)._database_model
        col_type = model_cls.weights.property.columns[0].type

        assert isinstance(col_type, psql.ARRAY)
        assert isinstance(col_type.item_type, sa_types.Float)


@pytest.mark.postgresql
class TestFieldSpecArrayPersistence:
    """End-to-end persistence tests for List fields with FieldSpec content_type."""

    def test_list_of_dict_roundtrip(self, test_domain):
        test_domain.register(DictListAggregate)

        model_cls = test_domain.repository_for(DictListAggregate)._database_model
        agg = DictListAggregate(
            label="test", payloads=[{"key": "val"}, {"key2": "val2"}]
        )
        model_obj = model_cls.from_entity(agg)
        copy = model_cls.to_entity(model_obj)

        assert copy.payloads == [{"key": "val"}, {"key2": "val2"}]

    def test_list_of_string_roundtrip(self, test_domain):
        test_domain.register(StringListAggregate)

        model_cls = test_domain.repository_for(StringListAggregate)._database_model
        agg = StringListAggregate(label="test", tags=["alpha", "beta"])
        model_obj = model_cls.from_entity(agg)
        copy = model_cls.to_entity(model_obj)

        assert copy.tags == ["alpha", "beta"]

    def test_list_of_integer_roundtrip(self, test_domain):
        test_domain.register(IntListAggregate)

        model_cls = test_domain.repository_for(IntListAggregate)._database_model
        agg = IntListAggregate(label="test", scores=[10, 20, 30])
        model_obj = model_cls.from_entity(agg)
        copy = model_cls.to_entity(model_obj)

        assert copy.scores == [10, 20, 30]

    def test_list_of_dict_full_persistence(self, test_domain):
        test_domain.register(DictListAggregate)

        agg = DictListAggregate(label="persisted", payloads=[{"a": 1}, {"b": 2}])
        current_domain.repository_for(DictListAggregate).add(agg)

        refreshed = current_domain.repository_for(DictListAggregate).get(agg.id)
        assert refreshed.payloads == [{"a": 1}, {"b": 2}]

    def test_list_of_string_full_persistence(self, test_domain):
        test_domain.register(StringListAggregate)

        agg = StringListAggregate(label="persisted", tags=["x", "y"])
        current_domain.repository_for(StringListAggregate).add(agg)

        refreshed = current_domain.repository_for(StringListAggregate).get(agg.id)
        assert refreshed.tags == ["x", "y"]

    def test_list_of_integer_full_persistence(self, test_domain):
        test_domain.register(IntListAggregate)

        agg = IntListAggregate(label="persisted", scores=[42, 99])
        current_domain.repository_for(IntListAggregate).add(agg)

        refreshed = current_domain.repository_for(IntListAggregate).get(agg.id)
        assert refreshed.scores == [42, 99]
