import pytest

from datetime import datetime, date

from protean import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields.basic import (
    List,
    String,
    Integer,
    Boolean,
    Date,
    DateTime,
    Float,
    Dict,
)
from protean.fields.embedded import ValueObject


class TestListFieldContentType:
    def test_list_field_with_string_content_type(self):
        field = List(content_type=String)
        value = ["hello", "world"]
        assert field._cast_to_type(value) == value

        value = ["hello", 123]
        assert field._cast_to_type(value) == ["hello", "123"]

    def test_list_field_with_integer_content_type(self):
        field = List(content_type=Integer)
        value = [1, 2, 3]
        assert field._cast_to_type(value) == value

        value = [1, "hello"]
        with pytest.raises(ValidationError):
            field._cast_to_type(value)

    def test_list_field_with_boolean_content_type(self):
        field = List(content_type=Boolean)
        value = [True, False, True]
        assert field._cast_to_type(value) == value

        value = [True, "hello"]
        with pytest.raises(ValidationError):
            field._cast_to_type(value)

    def test_list_field_with_date_content_type(self):
        field = List(content_type=Date)
        value = ["2023-05-01", "2023-06-15"]
        assert field._cast_to_type(value) == [date.fromisoformat(d) for d in value]

        value = ["2023-05-01", "invalid"]
        with pytest.raises(ValidationError):
            field._cast_to_type(value)

    def test_list_field_with_datetime_content_type(self):
        field = List(content_type=DateTime)
        value = ["2023-05-01T12:00:00", "2023-06-15T18:30:00"]
        assert field._cast_to_type(value) == [datetime.fromisoformat(d) for d in value]

        value = ["2023-05-01T12:00:00", "invalid"]
        with pytest.raises(ValidationError):
            field._cast_to_type(value)

    def test_list_field_with_float_content_type(self):
        field = List(content_type=Float)
        value = [1.2, 3.4, 5.6]
        assert field._cast_to_type(value) == value

        value = [1.2, "hello"]
        with pytest.raises(ValidationError):
            field._cast_to_type(value)

    def test_list_field_with_dict_content_type(self):
        field = List(content_type=Dict)
        value = [{"a": 1}, {"b": 2}]
        assert field._cast_to_type(value) == value

        value = [{"a": 1}, "hello"]
        with pytest.raises(ValidationError):
            field._cast_to_type(value)

    def test_list_field_with_invalid_content_type(self):
        with pytest.raises(ValidationError):
            List(content_type=int)

    def test_list_field_with_non_list_value(self):
        field = List(content_type=String)
        value = "hello"
        with pytest.raises(ValidationError):
            field._cast_to_type(value)

    def test_list_field_with_value_object_content_type(self):
        class VO(BaseValueObject):
            foo = String()

        field = List(content_type=ValueObject(VO))
        value = [VO(foo="bar"), VO(foo="baz")]
        assert field._cast_to_type(value) == value


class TestListFieldAsDictWithDifferentContentTypes:
    def test_list_as_dict_with_string_content_type(self):
        field = List(content_type=String)
        value = ["hello", "world"]
        assert field.as_dict(value) == value

    def test_list_as_dict_with_integer_content_type(self):
        field = List(content_type=Integer)
        value = [1, 2, 3]
        assert field.as_dict(value) == value

    def test_list_as_dict_with_float_content_type(self):
        field = List(content_type=Float)
        value = [1.2, 3.4, 5.6]
        assert field.as_dict(value) == value

    def test_list_as_dict_with_boolean_content_type(self):
        field = List(content_type=Boolean)
        value = [True, False, True]
        assert field.as_dict(value) == value

    def test_list_as_dict_with_date_content_type(self):
        field = List(content_type=Date)
        value = [date(2023, 4, 1), date(2023, 4, 2)]
        assert field.as_dict(value) == [str(d) for d in value]

    def test_list_as_dict_with_datetime_content_type(self):
        field = List(content_type=DateTime)
        value = [datetime(2023, 4, 1, 10, 30), datetime(2023, 4, 2, 11, 45)]
        assert field.as_dict(value) == [str(dt) for dt in value]

    def test_list_field_with_dict_content_type(self):
        field = List(content_type=Dict)
        value = [{"a": 1}, {"b": 2}]
        assert field.as_dict(value) == value

    def test_list_as_dict_with_value_object_content_type(self):
        class VO(BaseValueObject):
            foo = String()

        field = List(content_type=ValueObject(VO))
        value = [VO(foo="bar"), VO(foo="baz")]
        assert field.as_dict(value) == [{"foo": "bar"}, {"foo": "baz"}]
