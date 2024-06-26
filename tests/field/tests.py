"""Test Field Functionality"""

import pytest

from protean.exceptions import ValidationError
from protean.fields import Field


class DummyStringField(Field):
    """This is a dummy Field class for testing"""

    default_error_messages = {
        "invalid_type": "Field value must be of str type.",
        "invalid_type_formatted": "Field value must be of {type} type.",
    }

    def _cast_to_type(self, value: str):
        """Value must me a string type"""
        if not isinstance(value, str):
            self.fail("invalid_type")
        return value

    def as_dict(self, value: str):
        return value


class MinLengthValidator:
    def __init__(self, min_length):
        self.min_length = min_length
        self.error = f"Ensure this value has at least " f"{self.min_length} character."

    def __call__(self, value):
        if len(value) < self.min_length:
            raise ValidationError(self.error)


class TestField:
    def test_init(self):
        """Test successful String Field initialization"""

        name = DummyStringField()
        assert name is not None

    def test_required(self):
        """Test errors if required field has no value"""

        with pytest.raises(ValidationError):
            name = DummyStringField(required=True)
            name._load(None)

    def test_defaults(self):
        """Test default value is set when no value is supplied"""
        # Test with default value as constant
        name = DummyStringField(default="dummy")
        assert name._load("") == "dummy"

        # Test with default value as callable
        name = DummyStringField(default=lambda: "dummy")
        assert name._load("") == "dummy"

    def test_type_validation(self):
        """Test type checking validation for the Field"""
        with pytest.raises(ValidationError):
            name = DummyStringField()
            name._load(1)

    def test_validators(self):
        """Test custom validators defined for the field"""

        with pytest.raises(ValidationError):
            name = DummyStringField(validators=[MinLengthValidator(min_length=5)])
            name._load("Dum")

    def test_error_message(self):
        """Test that proper error message is generated"""

        # Test the basic error message
        try:
            name = DummyStringField(required=True)
            name._load(None)
        except ValidationError as err:
            assert err.messages == {"unlinked": [name.error_messages["required"]]}

        # Test overriding of error message
        try:
            name = DummyStringField()
            name._load(1)
        except ValidationError as err:
            assert err.messages == {"unlinked": ["Field value must be of str type."]}

        # Test multiple error messages
        try:
            name = DummyStringField(
                validators=[
                    MinLengthValidator(min_length=5),
                    MinLengthValidator(min_length=5),
                ]
            )
            name._load("Dum")
        except ValidationError as err:
            assert err.messages == {
                "unlinked": [
                    "Ensure this value has at least 5 character.",
                    "Ensure this value has at least 5 character.",
                ]
            }

    def test_default_validators(self):
        """Test that default validators for a Field are called"""

        def medium_string_validator(value):
            """Function checks the max length of a field"""
            if len(value) > 15:
                raise ValidationError("Value cannot be more than 15 characters long.")

        DummyStringField.default_validators = [medium_string_validator]
        with pytest.raises(ValidationError):
            name = DummyStringField()
            name._load("Dummy Dummy Dummy")

    def test_repr(self):
        """Test that Field repr is generated correctly"""

        name = DummyStringField()
        assert repr(name) == "DummyStringField()"

        name = DummyStringField(required=True)
        assert repr(name) == "DummyStringField(required=True)"

        name = DummyStringField(default="dummy")
        assert repr(name) == "DummyStringField(default='dummy')"

        name = DummyStringField(required=True, default="dummy")
        assert repr(name) == "DummyStringField(required=True, default='dummy')"

    def test_fail_method(self):
        """Test that Field fail method raises a ValidationError"""

        name = DummyStringField()
        with pytest.raises(ValidationError) as exc:
            name.fail("invalid_type")

        assert exc.value.messages == {"unlinked": ["Field value must be of str type."]}

        with pytest.raises(ValidationError) as exc:
            name.fail("unlinked")

        assert exc.value.messages == {
            "unlinked": [
                "ValidationError raised by `DummyStringField`, but error key "
                "`unlinked` does not exist in the `error_messages` dictionary."
            ]
        }

        # Test that error message is formatted correctly
        with pytest.raises(ValidationError) as exc:
            name.fail("invalid_type_formatted", type="int")

        assert exc.value.messages == {"unlinked": ["Field value must be of int type."]}
