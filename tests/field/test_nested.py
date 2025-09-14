from protean.fields import Nested


def test_nested_field_repr_and_str():
    nested_obj1 = Nested("schema1")
    nested_obj2 = Nested("schema1", many=True, required=True)
    nested_obj3 = Nested("schema1", default={"name": "John Doe"})
    nested_obj4 = Nested("schema1", required=True, default={"name": "John Doe"})

    assert repr(nested_obj1) == str(nested_obj1) == "Nested('schema1')"
    assert repr(nested_obj2) == str(nested_obj2) == "Nested('schema1', required=True)"
    assert (
        repr(nested_obj3)
        == str(nested_obj3)
        == "Nested('schema1', default={'name': 'John Doe'})"
    )
    assert (
        repr(nested_obj4)
        == str(nested_obj4)
        == "Nested('schema1', required=True, default={'name': 'John Doe'})"
    )


def test_nested_field_repr_without_schema_name():
    """Test Nested field repr when schema_name is None or empty"""
    nested_obj_none = Nested(None)
    nested_obj_empty = Nested("")
    nested_obj_none_with_required = Nested(None, required=True)

    # When schema_name is None or empty, it should not be included in repr
    assert "None" not in repr(nested_obj_none)
    assert "''" not in repr(nested_obj_empty)
    assert repr(nested_obj_none_with_required) == "Nested(required=True)"


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
