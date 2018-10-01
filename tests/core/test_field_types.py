""" Test cases for all available field type implementations"""

import pytest  # pylint: disable=E0401
from protean.core import field
from protean.core.exceptions import ValidationError


class TestStringField:
    """ Test the String Field Implementation"""

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
