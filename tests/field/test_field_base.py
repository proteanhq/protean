"""Tests for the legacy Field class in fields/base.py."""

import enum

import pytest

from protean.exceptions import ValidationError
from protean.fields.base import Field


# ---------------------------------------------------------------------------
# Concrete Field subclass for testing (Field is abstract)
# ---------------------------------------------------------------------------
class ConcreteField(Field):
    """Minimal concrete Field subclass for testing."""

    def _cast_to_type(self, value):
        return value

    def as_dict(self, value):
        return value


# ---------------------------------------------------------------------------
# Tests: _generic_param_values_for_repr
# ---------------------------------------------------------------------------
class TestFieldReprParams:
    def test_description_in_repr(self):
        """description appears in repr."""
        field = ConcreteField(description="A test field")
        values = field._generic_param_values_for_repr()
        assert "description='A test field'" in values

    def test_identifier_in_repr(self):
        """identifier=True appears in repr."""
        field = ConcreteField(identifier=True)
        values = field._generic_param_values_for_repr()
        assert "identifier=True" in values

    def test_referenced_as_in_repr(self):
        """referenced_as appears in repr."""
        field = ConcreteField(referenced_as="alt_name")
        values = field._generic_param_values_for_repr()
        assert "referenced_as='alt_name'" in values

    def test_non_string_default_in_repr(self):
        """Non-string non-callable default in repr."""
        field = ConcreteField(default=42)
        values = field._generic_param_values_for_repr()
        assert "default=42" in values


# ---------------------------------------------------------------------------
# Tests: __delete__
# ---------------------------------------------------------------------------
class TestFieldDelete:
    def test_field_delete(self):
        """__delete__ removes value from instance __dict__."""
        field = ConcreteField()
        field.field_name = "test_field"

        class FakeInstance:
            pass

        instance = FakeInstance()
        instance.__dict__["test_field"] = "some_value"
        field.__delete__(instance)
        assert "test_field" not in instance.__dict__


# ---------------------------------------------------------------------------
# Tests: _run_validators with empty value
# ---------------------------------------------------------------------------
class TestFieldRunValidators:
    def test_run_validators_with_empty_value_returns_early(self):
        """_run_validators returns early for empty values."""
        field = ConcreteField()
        field.field_name = "test_field"
        # None is an empty value, should return without running validators
        field._run_validators(None)


# ---------------------------------------------------------------------------
# Tests: _clone
# ---------------------------------------------------------------------------
class TestFieldClone:
    def test_clone_preserves_attributes(self):
        """_clone creates a new Field with same attributes."""
        field = ConcreteField(
            referenced_as="test_ref",
            description="A field",
            identifier=False,
            default="hello",
            required=True,
            unique=False,
            validators=[],
        )
        cloned = field._clone()
        assert cloned is not field
        assert type(cloned) is type(field)
        assert cloned.referenced_as == field.referenced_as
        assert cloned.description == field.description
        assert cloned.default == field.default
        assert cloned.required == field.required


# ---------------------------------------------------------------------------
# Tests: _load with choices
# ---------------------------------------------------------------------------
class TestFieldLoadWithChoices:
    def test_load_with_enum_choices(self):
        """Enum choices validation."""

        class Color(enum.Enum):
            RED = "red"
            GREEN = "green"
            BLUE = "blue"

        field = ConcreteField(choices=Color)
        field.field_name = "color"
        # Valid enum member
        assert field._load(Color.RED) == "red"
        # Valid string value
        assert field._load("green") == "green"

    def test_load_with_invalid_enum_choice(self):
        """Invalid choice raises ValidationError."""

        class Status(enum.Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"

        field = ConcreteField(choices=Status)
        field.field_name = "status"
        with pytest.raises(ValidationError):
            field._load("unknown")

    def test_load_with_list_choices(self):
        """List/tuple choices validation."""
        field = ConcreteField(choices=["a", "b", "c"])
        field.field_name = "letter"
        assert field._load("a") == "a"
        with pytest.raises(ValidationError):
            field._load("z")

    def test_load_with_none_returns_none(self):
        """None value when not required returns None."""
        field = ConcreteField(required=False)
        field.field_name = "optional"
        assert field._load(None) is None
