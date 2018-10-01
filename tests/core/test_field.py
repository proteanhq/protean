from protean.core.field import Field
from protean.core.exceptions import ValidationError
import pytest


class String(Field):
    """This is a dummy Field class for testing"""

    default_error_messages = {
        'invalid_type': 'Field value must be of str type.',
    }

    def validate_type(self, value: str):
        if type(value) != str:
            self.fail('invalid_type')
        return value


class MinLengthValidator:
    def __init__(self, min_length):
        self.min_length = min_length
        self.error = f'Ensure this value has at least ' \
                     f'{self.min_length} character.'

    def __call__(self, value):
        if len(value) < self.min_length:
            raise ValidationError(self.error)


class TestField:

    def test_init(self):
        """Test successful String Field initialization"""

        name = String()
        assert name is not None

    def test_required(self):
        """Test errors if required field has no value"""

        with pytest.raises(ValidationError):
            name = String(required=True)
            name.validate(None)

    def test_defaults(self):
        """ Test default value is set when no value is supplied"""
        # Test with default value as constant
        name = String(default='dummy')
        name.validate('')
        assert name.value == 'dummy'

        # Test with default value as callable
        name = String(default=lambda: 'dummy')
        name.validate('')
        assert name.value == 'dummy'

    def test_type_validation(self):
        """ Test type checking validation for the Field"""
        with pytest.raises(ValidationError):
            name = String()
            name.validate(1)

    def test_validators(self):
        """ Test custom validators defined for the field"""

        with pytest.raises(ValidationError):
            name = String(
                validators=[MinLengthValidator(min_length=5)])
            name.validate('Dum')

    def test_error_message(self):
        """ Test that proper error message is generated"""

        # Test the basic error message
        try:
            name = String(required=True)
            name.validate(None)
        except ValidationError as err:
            assert err.n_messages == {
                '_entity': [name.error_messages['required']]}

        # Test overriding of error message
        try:
            name = String()
            name.validate(1)
        except ValidationError as err:
            assert err.n_messages == {
                '_entity': ['Field value must be of str type.']}

        # Test multiple error messages
        try:
            name = String(
                validators=[MinLengthValidator(min_length=5),
                            MinLengthValidator(min_length=5)])
            name.validate('Dum')
        except ValidationError as err:
            assert err.n_messages == {
                '_entity': ['Ensure this value has at least 5 character.',
                            'Ensure this value has at least 5 character.']}

    def test_default_validators(self):
        """ Test that default validators for a Field are called"""
        def medium_string_validator(value):
            """Function checks the max length of a field"""
            if len(value) > 15:
                raise ValidationError(
                    'Value cannot be more than 15 characters long.')
        String.default_validators = [medium_string_validator]
        with pytest.raises(ValidationError):
            name = String()
            name.validate('Dummy Dummy Dummy')
