"""Test List field behavior through domain objects.

The List() factory function returns a FieldSpec. Validation happens
at the model level when a domain object is instantiated.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import Dict, Float, Integer, List, String
from protean.fields.embedded import ValueObject
from protean.fields.spec import FieldSpec


class TestListFieldContentType:
    def test_list_field_with_string_content_type(self):
        class VO(BaseValueObject):
            items: List(content_type=String)

        vo = VO(items=["hello", "world"])
        assert vo.items == ["hello", "world"]

    def test_list_field_with_integer_content_type(self):
        class VO(BaseValueObject):
            items: List(content_type=Integer)

        vo = VO(items=[1, 2, 3])
        assert vo.items == [1, 2, 3]

        with pytest.raises(ValidationError):
            VO(items=[1, "hello"])

    def test_list_field_with_float_content_type(self):
        class VO(BaseValueObject):
            items: List(content_type=Float)

        vo = VO(items=[1.2, 3.4, 5.6])
        assert vo.items == [1.2, 3.4, 5.6]

        with pytest.raises(ValidationError):
            VO(items=[1.2, "hello"])

    def test_list_field_with_non_list_value(self):
        class VO(BaseValueObject):
            items: List(content_type=String)

        with pytest.raises(ValidationError):
            VO(items="hello")

    def test_list_field_with_value_object_content_type(self):
        class InnerVO(BaseValueObject):
            foo: String()

        class OuterVO(BaseValueObject):
            items: List(content_type=ValueObject(InnerVO))

        vo = OuterVO(items=[InnerVO(foo="bar"), InnerVO(foo="baz")])
        assert len(vo.items) == 2

    def test_list_field_with_invalid_value_object(self):
        class NotAVO(BaseEntity):
            foo: String()

        with pytest.raises(Exception):
            List(content_type=ValueObject(NotAVO))

    def test_list_field_with_value_object_string_is_resolved(self, test_domain):
        class InnerVO(BaseValueObject):
            foo: String()

        class Foo(BaseAggregate):
            foos: List(content_type=ValueObject("InnerVO"))

        test_domain.register(InnerVO)
        test_domain.register(Foo)
        test_domain.init(traverse=False)

        # The original ValueObject descriptor is stored in __protean_field_meta__
        # After domain.init(), the string reference should be resolved to InnerVO
        field_meta = Foo.__protean_field_meta__["foos"]
        assert field_meta.content_type.value_object_cls == InnerVO


class TestListFieldThroughAggregates:
    """Test List field as_dict-like behavior through aggregate to_dict()."""

    def test_list_with_string_content_in_to_dict(self):
        class VO(BaseValueObject):
            items: List(content_type=String)

        vo = VO(items=["hello", "world"])
        assert vo.to_dict()["items"] == ["hello", "world"]

    def test_list_with_integer_content_in_to_dict(self):
        class VO(BaseValueObject):
            items: List(content_type=Integer)

        vo = VO(items=[1, 2, 3])
        assert vo.to_dict()["items"] == [1, 2, 3]

    def test_list_with_float_content_in_to_dict(self):
        class VO(BaseValueObject):
            items: List(content_type=Float)

        vo = VO(items=[1.2, 3.4, 5.6])
        assert vo.to_dict()["items"] == [1.2, 3.4, 5.6]

    def test_list_with_dict_content_in_to_dict(self):
        class VO(BaseValueObject):
            items: List(content_type=Dict)

        vo = VO(items=[{"a": 1}, {"b": 2}])
        assert vo.to_dict()["items"] == [{"a": 1}, {"b": 2}]

    def test_list_with_value_object_content_in_to_dict(self):
        class InnerVO(BaseValueObject):
            foo: String()

        class OuterVO(BaseValueObject):
            items: List(content_type=ValueObject(InnerVO))

        vo = OuterVO(items=[InnerVO(foo="bar"), InnerVO(foo="baz")])
        result = vo.to_dict()
        assert result["items"] == [{"foo": "bar"}, {"foo": "baz"}]


# ---------------------------------------------------------------------------
# Tests: List() factory with raw types and FieldSpec content
# ---------------------------------------------------------------------------
class TestListFieldFactory:
    def test_list_with_raw_type_content(self):
        """List() with a plain Python type as content_type."""
        spec = List(content_type=int)
        assert isinstance(spec, FieldSpec)
        assert spec.python_type == list[int]

    def test_list_with_fieldspec_non_union_type(self):
        """List(FieldSpec) where resolved type is not a Union."""
        # Integer(required=True) resolves to `int` (not Optional)
        spec = List(content_type=Integer(required=True))
        assert isinstance(spec, FieldSpec)
        assert spec.python_type == list[int]
