"""Tests for ValueObjectList field in fields/basic.py.

Covers:
- Unsupported content_type raises ValidationError
- _cast_to_type with non-list input
- _cast_to_type with ValueObject content
- _cast_to_type with primitive Python types
- as_dict with ValueObject content
- as_dict with datetime content
- as_dict with primitive content
"""

import datetime

import pytest

from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields.basic import ValueObjectList
from protean.fields.embedded import ValueObject


class TestValueObjectListInit:
    def test_unsupported_content_type_raises_error(self):
        """Line 56: ValidationError when content_type is not supported."""

        class Dummy:
            pass

        with pytest.raises(ValidationError) as exc_info:
            ValueObjectList(content_type=Dummy)
        assert "content_type" in exc_info.value.messages

    def test_supported_primitive_content_types(self):
        for ct in (bool, datetime.date, datetime.datetime, float, int, str, dict):
            field = ValueObjectList(content_type=ct)
            assert field.content_type is ct

    def test_value_object_content_type(self):
        class Inner(BaseValueObject):
            name: str | None = None

        vo = ValueObject(value_object_cls=Inner)
        field = ValueObjectList(content_type=vo)
        assert field.content_type is vo


class TestValueObjectListCastToType:
    def test_non_list_value_fails(self):
        """Lines 66-67: fail('invalid') when value is not a list."""
        field = ValueObjectList(content_type=str)
        with pytest.raises(ValidationError):
            field._cast_to_type("not a list")

    def test_value_object_content_type_cast(self):
        """Lines 69-76: ValueObject content type path - valid data."""

        class Inner(BaseValueObject):
            name: str | None = None

        vo = ValueObject(value_object_cls=Inner)
        field = ValueObjectList(content_type=vo)
        result = field._cast_to_type([{"name": "Alice"}, {"name": "Bob"}])
        assert len(result) == 2
        assert result[0].name == "Alice"
        assert result[1].name == "Bob"

    def test_value_object_content_type_invalid_data(self):
        """Lines 74-75: fail('invalid_content') for invalid VO data."""

        class Inner(BaseValueObject):
            name: str

        vo = ValueObject(value_object_cls=Inner)
        field = ValueObjectList(content_type=vo)
        with pytest.raises(ValidationError):
            field._cast_to_type(["not a valid vo input"])

    def test_primitive_content_type_cast(self):
        """Lines 78-85: Python primitive type cast."""
        field = ValueObjectList(content_type=int)
        result = field._cast_to_type([1, 2, 3])
        assert result == [1, 2, 3]

    def test_primitive_content_type_cast_coerces(self):
        """Primitive content type casts string to int."""
        field = ValueObjectList(content_type=int)
        result = field._cast_to_type(["1", "2", "3"])
        assert result == [1, 2, 3]

    def test_primitive_content_type_invalid_data(self):
        """Lines 83-84: fail('invalid_content') for bad primitive cast."""
        field = ValueObjectList(content_type=int)
        with pytest.raises(ValidationError):
            field._cast_to_type(["not_a_number"])


class TestValueObjectListAsDict:
    def test_as_dict_with_value_object_content(self):
        """Lines 89-90: ValueObject content path in as_dict."""

        class Inner(BaseValueObject):
            name: str | None = None

        vo = ValueObject(value_object_cls=Inner)
        field = ValueObjectList(content_type=vo)
        items = [Inner(name="Alice"), Inner(name="Bob")]
        result = field.as_dict(items)
        assert result == [{"name": "Alice"}, {"name": "Bob"}]

    def test_as_dict_with_datetime_content(self):
        """Lines 93-94: datetime content type path in as_dict."""
        field = ValueObjectList(content_type=datetime.datetime)
        dt1 = datetime.datetime(2024, 1, 1, 12, 0)
        dt2 = datetime.datetime(2024, 6, 15, 18, 30)
        result = field.as_dict([dt1, dt2])
        assert result == [str(dt1), str(dt2)]

    def test_as_dict_with_date_content(self):
        """datetime.date content type also uses str conversion."""
        field = ValueObjectList(content_type=datetime.date)
        d1 = datetime.date(2024, 1, 1)
        d2 = datetime.date(2024, 6, 15)
        result = field.as_dict([d1, d2])
        assert result == [str(d1), str(d2)]

    def test_as_dict_with_none_in_datetime_list(self):
        """datetime path handles None items."""
        field = ValueObjectList(content_type=datetime.datetime)
        result = field.as_dict([None])
        assert result == [None]

    def test_as_dict_with_primitive_content(self):
        """Line 96: primitive content returns list(value)."""
        field = ValueObjectList(content_type=str)
        result = field.as_dict(["hello", "world"])
        assert result == ["hello", "world"]

    def test_as_dict_with_int_content(self):
        field = ValueObjectList(content_type=int)
        result = field.as_dict([1, 2, 3])
        assert result == [1, 2, 3]


# ---------------------------------------------------------------------------
# Method field tests
# ---------------------------------------------------------------------------
class TestMethodField:
    def test_init(self):
        from protean.fields.basic import Method

        field = Method("get_full_name")
        assert field.method_name == "get_full_name"

    def test_cast_to_type_returns_value_as_is(self):
        from protean.fields.basic import Method

        field = Method("compute")
        assert field._cast_to_type(42) == 42
        assert field._cast_to_type("hello") == "hello"
        assert field._cast_to_type(None) is None

    def test_as_dict_returns_value_as_is(self):
        from protean.fields.basic import Method

        field = Method("compute")
        assert field.as_dict(42) == 42
        assert field.as_dict("hello") == "hello"


# ---------------------------------------------------------------------------
# Nested field tests
# ---------------------------------------------------------------------------
class TestNestedField:
    def test_init(self):
        from protean.fields.basic import Nested

        field = Nested("OrderItem")
        assert field.schema_name == "OrderItem"
        assert field.many is False

    def test_init_with_many(self):
        from protean.fields.basic import Nested

        field = Nested("OrderItem", many=True)
        assert field.schema_name == "OrderItem"
        assert field.many is True

    def test_cast_to_type_returns_value_as_is(self):
        from protean.fields.basic import Nested

        field = Nested("OrderItem")
        assert field._cast_to_type({"id": 1}) == {"id": 1}
        assert field._cast_to_type(None) is None

    def test_as_dict_returns_value_as_is(self):
        from protean.fields.basic import Nested

        field = Nested("OrderItem")
        assert field.as_dict({"id": 1}) == {"id": 1}

    def test_repr(self):
        from protean.fields.basic import Nested

        field = Nested("OrderItem")
        assert repr(field) == "Nested('OrderItem')"

    def test_repr_with_many(self):
        from protean.fields.basic import Nested

        field = Nested("OrderItem", many=True)
        assert repr(field) == "Nested('OrderItem', many=True)"

    def test_repr_without_schema_name(self):
        from protean.fields.basic import Nested

        field = Nested("")
        assert repr(field) == "Nested()"
