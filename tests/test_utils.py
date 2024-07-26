import pytest

from protean.exceptions import ConfigurationError
from protean.utils import convert_str_values_to_list, generate_identity, get_version


def test_convert_str_values_to_list():
    # Test when value is None
    assert convert_str_values_to_list(None) == []

    # Test when value is an empty string
    assert convert_str_values_to_list("") == []

    # Test when value is a non-empty string
    assert convert_str_values_to_list("test") == ["test"]

    # Test when value is a list of strings
    assert convert_str_values_to_list(["a", "b"]) == ["a", "b"]

    # Test when value is a list of integers
    assert convert_str_values_to_list([1, 2, 3]) == [1, 2, 3]

    # Test when value is a tuple
    assert convert_str_values_to_list((1, 2, 3)) == [1, 2, 3]

    # Test when value is a set
    assert convert_str_values_to_list({1, 2, 3}) == [1, 2, 3]

    # Test when value is a dictionary
    assert convert_str_values_to_list({"a": 1, "b": 2}) == ["a", "b"]

    # Test when value is an integer (not iterable)
    with pytest.raises(TypeError):
        convert_str_values_to_list(10)

    # Test when value is a float (not iterable)
    with pytest.raises(TypeError):
        convert_str_values_to_list(10.5)

    # Test when value is a boolean
    with pytest.raises(TypeError):
        convert_str_values_to_list(True)

    # Test when value is an object
    class TestObject:
        pass

    with pytest.raises(TypeError):
        convert_str_values_to_list(TestObject())


def test_unknown_identity_type_raises_exception():
    with pytest.raises(ConfigurationError) as exc:
        generate_identity(identity_type="foo")

    assert str(exc.value) == "Unknown Identity Type 'foo'"


def test_get_version():
    assert get_version() == "0.12.1"
