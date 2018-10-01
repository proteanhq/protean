""" Test cases for all available field type implementations"""

import pytest  # pylint: disable=E0401
from decimal import Decimal

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


class TestIntegerField:
    """ Test the Integer Field Implementation"""

    def test_init(self):
        """Test successful String Field initialization"""

        age = field.Integer()
        assert age is not None

    def test_type_validation(self):
        """ Test type checking validation for the Field"""
        with pytest.raises(ValidationError):
            age = field.Integer()
            age.validate('x')

    def test_min_value(self):
        """ Test minimum value validation for the integer field"""

        with pytest.raises(ValidationError):
            age = field.Integer(min_value=5)
            age.validate(3)

    def test_max_value(self):
        """ Test maximum value validation for the string field"""

        with pytest.raises(ValidationError):
            age = field.Integer(max_value=5)
            age.validate(6)

    def test_float_input(self):
        """ Test that floats and decimals are converted to integer"""

        age = field.Integer()
        age.validate(3.1)
        assert age.value == 3

        age.validate(Decimal(3.1))
        assert age.value == 3
