import pytest

from protean._deprecation import RemovedInProtean10Warning
from protean.fields import Nested


def test_nested_is_deprecated():
    """Instantiating a Nested field warns it is removed at v1.0.0."""
    # Match the concrete subject text so a copy-paste of the ``Method`` message
    # into ``Nested.__init__`` would fail this test.
    with pytest.warns(
        RemovedInProtean10Warning, match=r"`Nested` field is deprecated.*v1\.0\.0"
    ) as record:
        field = Nested("schema1")

    # ``Nested`` is a serializer field with no replacement element.
    assert any(
        "Serializer fields are no longer supported." in str(w.message) for w in record
    )
    # The field is still functional despite the deprecation.
    assert field.schema_name == "schema1"
    assert field._cast_to_type("x") == "x"


def test_nested_field_repr_and_str():
    nested_obj1 = Nested("schema1")
    nested_obj2 = Nested("schema1", many=True, required=True)
    nested_obj3 = Nested("schema1", default={"name": "John Doe"})
    nested_obj4 = Nested("schema1", required=True, default={"name": "John Doe"})

    assert repr(nested_obj1) == str(nested_obj1) == "Nested('schema1')"
    # Nested.__repr__ only shows schema_name and many, not required/default
    assert repr(nested_obj2) == str(nested_obj2) == "Nested('schema1', many=True)"
    assert repr(nested_obj3) == str(nested_obj3) == "Nested('schema1')"
    assert repr(nested_obj4) == str(nested_obj4) == "Nested('schema1')"


def test_nested_field_repr_without_schema_name():
    """Test Nested field repr when schema_name is None or empty"""
    nested_obj_none = Nested(None)
    nested_obj_empty = Nested("")
    nested_obj_none_with_required = Nested(None, required=True)

    # When schema_name is None or empty, it should not be included in repr
    assert "None" not in repr(nested_obj_none)
    assert "''" not in repr(nested_obj_empty)
    # Nested.__repr__ does not show required
    assert repr(nested_obj_none_with_required) == "Nested()"


def test_nested_cast_to_type():
    """Test that Nested._cast_to_type returns value as is"""
    nested_field = Nested("schema1")

    # Test with various value types
    assert nested_field._cast_to_type("test") == "test"
    assert nested_field._cast_to_type(123) == 123
    assert nested_field._cast_to_type(None) is None
    assert nested_field._cast_to_type({"key": "value"}) == {"key": "value"}
    assert nested_field._cast_to_type([1, 2, 3]) == [1, 2, 3]


def test_nested_as_dict():
    """Test that Nested.as_dict returns value as is"""
    nested_field = Nested("schema1")

    # Test with various value types
    assert nested_field.as_dict("test") == "test"
    assert nested_field.as_dict(123) == 123
    assert nested_field.as_dict(None) is None
    assert nested_field.as_dict({"key": "value"}) == {"key": "value"}
    assert nested_field.as_dict([1, 2, 3]) == [1, 2, 3]
