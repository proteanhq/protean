"""The SQLAlchemy type the adapter picks for embedded fields and array items.

These helpers are pure functions of a field object, so the tests call them
directly. Nothing here opens a connection.
"""

import typing

import pytest
import sqlalchemy.dialects.postgresql as psql
from sqlalchemy import types as sa_types

from protean.adapters.repository.sqlalchemy import (
    _field_mapping_for,
    _postgresql_array_item_type,
    _union_column_arm,
)
from protean.core.value_object import BaseValueObject
from protean.fields import Dict, Float, String
from protean.fields.basic import ValueObjectList
from protean.fields.embedded import ValueObject

pytestmark = pytest.mark.no_test_domain


class Address(BaseValueObject):
    street: String(max_length=50)


class TestFieldMappingForEmbeddedFields:
    def test_value_object_list_maps_to_pickle_type(self):
        field = ValueObjectList(content_type=ValueObject(Address))
        assert _field_mapping_for(field) is sa_types.PickleType

    def test_unknown_field_object_maps_to_string(self):
        assert _field_mapping_for(object()) is sa_types.String


class TestPostgresqlArrayItemType:
    def test_value_object_item_is_json_when_not_pickled(self):
        assert (
            _postgresql_array_item_type(ValueObject(Address), pickled=False)
            is psql.JSON
        )

    def test_value_object_item_is_pickle_type_when_pickled(self):
        assert (
            _postgresql_array_item_type(ValueObject(Address), pickled=True)
            is sa_types.PickleType
        )

    def test_value_object_class_item_is_pickle_type_when_pickled(self):
        assert _postgresql_array_item_type(Address, pickled=True) is sa_types.PickleType

    def test_field_spec_item_maps_its_python_type(self):
        assert _postgresql_array_item_type(Float(), pickled=False) is sa_types.Float

    def test_field_spec_union_item_maps_the_first_arm(self):
        # Dict() resolves to ``dict | list``; the item takes the ``dict`` column.
        assert _postgresql_array_item_type(Dict(), pickled=False) is sa_types.JSON

    def test_plain_type_item_maps_through_the_type_table(self):
        assert _postgresql_array_item_type(int, pickled=False) is sa_types.Integer

    def test_non_type_item_falls_back_to_string(self):
        assert _postgresql_array_item_type(None, pickled=False) is sa_types.String


class TestUnionColumnArm:
    def test_optional_unwraps_to_its_arm(self):
        assert _union_column_arm(str | None) is str

    def test_optional_literal_keeps_the_literal(self):
        literal = typing.Literal["a", "b"]
        assert _union_column_arm(literal | None) == literal

    def test_union_led_by_literal_has_no_arm(self):
        assert _union_column_arm(typing.Literal[1] | str) is None

    def test_non_union_comes_back_unchanged(self):
        assert _union_column_arm(int) is int
