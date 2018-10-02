""" Test cases for all available field type implementations"""

from decimal import Decimal

import pytest

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
        """Test successful Integer Field initialization"""

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
        """ Test maximum value validation for the integer field"""

        with pytest.raises(ValidationError):
            age = field.Integer(max_value=5)
            age.validate(6)

    def test_float_input(self):
        """ Test that floats and decimals are converted to integer"""

        age = field.Integer()
        assert age.validate(3.1) == 3

        assert age.validate(Decimal(3.1)) == 3


class TestFloatField:
    """ Test the Float Field Implementation"""

    def test_init(self):
        """Test successful Float Field initialization"""

        score = field.Float()
        assert score is not None

    def test_type_validation(self):
        """ Test type checking validation for the Field"""
        with pytest.raises(ValidationError):
            score = field.Float()
            score.validate('x')

    def test_min_value(self):
        """ Test minimum value validation for the float field"""

        with pytest.raises(ValidationError):
            score = field.Float(min_value=5.4)
            score.validate(5.3)

    def test_max_value(self):
        """ Test maximum value validation for the float field"""

        with pytest.raises(ValidationError):
            score = field.Float(max_value=5.5)
            score.validate(5.6)

    def test_float_input(self):
        """ Test that integers and decimals are converted to integer"""

        score = field.Float()
        assert score.validate(3) == 3.0

        assert score.validate(Decimal(3.1)) == 3.1


class TestBooleanField:
    """ Test the Boolean Field Implementation"""

    def test_init(self):
        """Test successful Boolean Field initialization"""

        married = field.Boolean()
        assert married is not None
        assert married.validate(True) is True

    def test_type_validation(self):
        """ Test type checking validation for the Field"""
        with pytest.raises(ValidationError):
            married = field.Boolean()
            married.validate('x')


class TestListField:
    """ Test the List Field Implementation"""

    def test_init(self):
        """Test successful List Field initialization"""

        tags = field.List()
        assert tags is not None

        assert tags.validate(['x', 'y', 'z']) == ['x', 'y', 'z']

    def test_type_validation(self):
        """ Test type checking validation for the Field"""
        with pytest.raises(ValidationError):
            tags = field.Boolean()
            tags.validate('x')


class TestDictField:
    """ Test the Dict Field Implementation"""

    def test_init(self):
        """Test successful Dict Field initialization"""

        add_info = field.Dict()
        assert add_info is not None

        value = add_info.validate({'available': 'weekdays'})
        assert value == {'available': 'weekdays'}

    def test_type_validation(self):
        """ Test type checking validation for the Field"""
        with pytest.raises(ValidationError):
            add_info = field.Dict()
            add_info.validate('x')
