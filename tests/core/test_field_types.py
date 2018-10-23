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
            name.load(1)

    def test_min_length(self):
        """ Test minimum length validation for the string field"""

        with pytest.raises(ValidationError):
            name = field.String(min_length=5)
            name.load('Dum')

    def test_max_length(self):
        """ Test maximum length validation for the string field"""

        with pytest.raises(ValidationError):
            name = field.String(max_length=5)
            name.load('Dummy Dummy')


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
            age.load('x')

    def test_min_value(self):
        """ Test minimum value validation for the integer field"""

        with pytest.raises(ValidationError):
            age = field.Integer(min_value=5)
            age.load(3)

    def test_max_value(self):
        """ Test maximum value validation for the integer field"""

        with pytest.raises(ValidationError):
            age = field.Integer(max_value=5)
            age.load(6)


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
            score.load('x')

    def test_min_value(self):
        """ Test minimum value validation for the float field"""

        with pytest.raises(ValidationError):
            score = field.Float(min_value=5.4)
            score.load(5.3)

    def test_max_value(self):
        """ Test maximum value validation for the float field"""

        with pytest.raises(ValidationError):
            score = field.Float(max_value=5.5)
            score.load(5.6)


class TestBooleanField:
    """ Test the Boolean Field Implementation"""

    def test_init(self):
        """Test successful Boolean Field initialization"""

        married = field.Boolean()
        assert married is not None
        assert married.load(True) is True

    def test_type_validation(self):
        """ Test type checking validation for the Field"""
        with pytest.raises(ValidationError):
            married = field.Boolean()
            married.load('x')


class TestListField:
    """ Test the List Field Implementation"""

    def test_init(self):
        """Test successful List Field initialization"""

        tags = field.List()
        assert tags is not None

        assert tags.load(['x', 'y', 'z']) == ['x', 'y', 'z']

    def test_type_validation(self):
        """ Test type checking validation for the Field"""
        with pytest.raises(ValidationError):
            tags = field.Boolean()
            tags.load('x')


class TestDictField:
    """ Test the Dict Field Implementation"""

    def test_init(self):
        """Test successful Dict Field initialization"""

        add_info = field.Dict()
        assert add_info is not None

        value = add_info.load({'available': 'weekdays'})
        assert value == {'available': 'weekdays'}

    def test_type_validation(self):
        """ Test type checking validation for the Field"""
        with pytest.raises(ValidationError):
            add_info = field.Dict()
            add_info.load('x')


class TestAutoField:
    """ Test the Auto Field Implementation"""

    def test_init(self):
        """Test successful Dict Field initialization"""

        add_info = field.Auto()
        assert add_info is not None

        value = add_info.load(1)
        assert value == 1

    def test_validation(self):
        """ Test validation for the Auto Field"""
        add_info = field.Auto(required=True)
        add_info.load(None)
