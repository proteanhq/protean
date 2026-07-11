import pytest

from protean.exceptions import ConfigurationError
from protean.utils import (
    _convert_str_values_to_list,
    _generate_identity,
    clone_class,
    get_version,
)


def test_convert_str_values_to_list():
    # Test when value is None
    assert _convert_str_values_to_list(None) == []

    # Test when value is an empty string
    assert _convert_str_values_to_list("") == []

    # Test when value is a non-empty string
    assert _convert_str_values_to_list("test") == ["test"]

    # Test when value is a list of strings
    assert _convert_str_values_to_list(["a", "b"]) == ["a", "b"]

    # Test when value is a list of integers
    assert _convert_str_values_to_list([1, 2, 3]) == [1, 2, 3]

    # Test when value is a tuple
    assert _convert_str_values_to_list((1, 2, 3)) == [1, 2, 3]

    # Test when value is a set
    assert _convert_str_values_to_list({1, 2, 3}) == [1, 2, 3]

    # Test when value is a dictionary
    assert _convert_str_values_to_list({"a": 1, "b": 2}) == ["a", "b"]

    # Test when value is an integer (not iterable)
    with pytest.raises(TypeError):
        _convert_str_values_to_list(10)

    # Test when value is a float (not iterable)
    with pytest.raises(TypeError):
        _convert_str_values_to_list(10.5)

    # Test when value is a boolean
    with pytest.raises(TypeError):
        _convert_str_values_to_list(True)

    # Test when value is an object
    class TestObject:
        pass

    with pytest.raises(TypeError):
        _convert_str_values_to_list(TestObject())


def test_unknown_identity_type_raises_exception():
    with pytest.raises(ConfigurationError) as exc:
        _generate_identity(identity_type="foo")

    assert str(exc.value) == "Unknown Identity Type 'foo'"


def test_unknown_identity_strategy_raises_exception():
    """Unknown identity strategy raises ConfigurationError."""
    with pytest.raises(ConfigurationError) as exc:
        _generate_identity(identity_strategy="unknown")
    assert "Unknown Identity Strategy" in str(exc.value)


def test_function_identity_strategy_with_invalid_function():
    """Invalid identity function raises ConfigurationError."""
    with pytest.raises(ConfigurationError) as exc:
        _generate_identity(
            identity_strategy="function", identity_function="not_callable"
        )
    assert "Identity function is invalid" in str(exc.value)


def test_function_identity_strategy_with_valid_function():
    """Valid identity function is called."""
    counter = [0]

    def custom_id_fn():
        counter[0] += 1
        return f"custom-{counter[0]}"

    result = _generate_identity(
        identity_strategy="function", identity_function=custom_id_fn
    )
    assert result == "custom-1"


def test_get_version():
    """get_version returns a version string."""
    version = get_version()
    assert isinstance(version, str)
    assert len(version) > 0


# ---------------------------------------------------------------------------
# Tests: clone_class with __slots__ as string
# ---------------------------------------------------------------------------
class TestCloneClassSlotsAsString:
    def test_clone_class_with_string_slots(self):
        """clone_class handles __slots__ as a single string."""

        class SlottedClass:
            __slots__ = "value"

            def __init__(self, value):
                self.value = value

        cloned = clone_class(SlottedClass, "ClonedSlotted")
        assert cloned.__name__ == "ClonedSlotted"
        instance = cloned(42)
        assert instance.value == 42
