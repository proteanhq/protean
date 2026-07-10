from datetime import datetime, timezone

import pytest

from protean._deprecation import RemovedInProtean10Warning
from protean.fields import Method


def utc_now():
    return datetime.now(timezone.utc)


def test_method_is_deprecated():
    """Instantiating a Method field warns it is removed at v1.0.0."""
    # Match the concrete subject text so a copy-paste of the ``Nested`` message
    # into ``Method.__init__`` would fail this test.
    with pytest.warns(
        RemovedInProtean10Warning, match=r"`Method` field is deprecated.*v1\.0\.0"
    ) as record:
        field = Method("fake_method")

    # ``Method`` is a serializer field with no replacement element.
    assert any(
        "Serializer fields are no longer supported." in str(w.message) for w in record
    )
    # The field is still functional despite the deprecation.
    assert field.method_name == "fake_method"
    assert field._cast_to_type("x") == "x"


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
