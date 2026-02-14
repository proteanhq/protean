from datetime import datetime, timezone

from protean.fields import Method


def utc_now():
    return datetime.now(timezone.utc)


def test_method_repr_and_str():
    method_obj1 = Method("fake_method")
    method_obj2 = Method("fake_method", required=True)
    method_obj4 = Method("fake_method", required=True, default=utc_now)

    assert repr(method_obj1) == str(method_obj1) == "Method()"
    assert repr(method_obj2) == str(method_obj2) == "Method(required=True)"
    assert (
        repr(method_obj4)
        == str(method_obj4)
        == "Method(required=True, default=utc_now)"
    )


def test_method_cast_to_type():
    """Test that Method._cast_to_type returns value as is"""
    method_field = Method("fake_method")

    # Test with various value types
    assert method_field._cast_to_type("test") == "test"
    assert method_field._cast_to_type(123) == 123
    assert method_field._cast_to_type(None) is None
    assert method_field._cast_to_type({"key": "value"}) == {"key": "value"}
    assert method_field._cast_to_type([1, 2, 3]) == [1, 2, 3]


def test_method_as_dict():
    """Test that Method.as_dict returns value as is"""
    method_field = Method("fake_method")

    # Test with various value types
    assert method_field.as_dict("test") == "test"
    assert method_field.as_dict(123) == 123
    assert method_field.as_dict(None) is None
    assert method_field.as_dict({"key": "value"}) == {"key": "value"}
    assert method_field.as_dict([1, 2, 3]) == [1, 2, 3]
