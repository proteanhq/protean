from protean.core import field
from protean.core.exceptions import ValidationError
import pytest


class TestStringField:

    def test_init(self):
        """Test successful String Field initialization"""

        name = field.String()
        assert name is not None

    def test_type_validation(self):
        """ Test type checking validation for the Field"""
        with pytest.raises(ValidationError):
            name = field.String()
            name.validate(1)

    def test_min_length(self):
        """ Test minimum length validation for the string field"""

        with pytest.raises(ValidationError):
            name = field.String(min_length=5)
            name.validate('Dum')

    def test_max_length(self):
        """ Test maximum length validation for the string field"""

        with pytest.raises(ValidationError):
            name = field.String(max_length=5)
            name.validate('Dummy Dummy')

    # def test_error_message(self):
    #     """ Test that proper error message is generated"""
    #
    #     # Test the basic error message
    #     try:
    #         name = String(required=True)
    #         name.validate(None)
    #     except ValidationError as err:
    #         assert err.n_messages == {
    #             '_entity': [name.error_messages['required']]}
    #
    #     # Test overriding of error message
    #     try:
    #         name = String()
    #         name.validate(1)
    #     except ValidationError as err:
    #         assert err.n_messages == {
    #             '_entity': ['Field value must be of str type.']}
    #
    #     # Test multiple error messages
    #     try:
    #         name = String(
    #             validators=[MinLengthValidator(min_length=5),
    #                         MinLengthValidator(min_length=5)])
    #         name.validate('Dum')
    #     except ValidationError as err:
    #         assert err.n_messages == {
    #             '_entity': ['Ensure this value has at least 5 character.',
    #                         'Ensure this value has at least 5 character.']}
    #
    # def test_default_validators(self):
    #     def medium_string_validator(value):
    #         # Function checks the max length of a field
    #         if len(value) > 15:
    #             raise ValidationError(
    #                 'Value cannot be more than 15 characters long.')
    #     String.default_validators = [medium_string_validator]
    #     with pytest.raises(ValidationError):
    #         name = String()
    #         name.validate('Dummy Dummy Dummy')
