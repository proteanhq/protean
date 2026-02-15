import pytest

from protean.exceptions import ConfigurationError
from protean.utils import (
    clone_class,
    convert_str_values_to_list,
    generate_identity,
    get_version,
)


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


def test_unknown_identity_strategy_raises_exception():
    """Line 449: Unknown identity strategy raises ConfigurationError."""
    with pytest.raises(ConfigurationError) as exc:
        generate_identity(identity_strategy="unknown")
    assert "Unknown Identity Strategy" in str(exc.value)


def test_function_identity_strategy_with_invalid_function():
    """Line 446: Invalid identity function raises ConfigurationError."""
    with pytest.raises(ConfigurationError) as exc:
        generate_identity(
            identity_strategy="function", identity_function="not_callable"
        )
    assert "Identity function is invalid" in str(exc.value)


def test_function_identity_strategy_with_valid_function():
    """Lines 443-444: Valid identity function is called."""
    counter = [0]

    def custom_id_fn():
        counter[0] += 1
        return f"custom-{counter[0]}"

    result = generate_identity(
        identity_strategy="function", identity_function=custom_id_fn
    )
    assert result == "custom-1"


def test_get_version():
    """Line 72: get_version returns a version string."""
    version = get_version()
    assert isinstance(version, str)
    assert len(version) > 0


# ---------------------------------------------------------------------------
# Tests: clone_class with __slots__ as string
# ---------------------------------------------------------------------------
class TestCloneClassSlotsAsString:
    def test_clone_class_with_string_slots(self):
        """Lines 524-525: clone_class handles __slots__ as a single string."""

        class SlottedClass:
            __slots__ = "value"

            def __init__(self, value):
                self.value = value

        cloned = clone_class(SlottedClass, "ClonedSlotted")
        assert cloned.__name__ == "ClonedSlotted"
        instance = cloned(42)
        assert instance.value == 42
