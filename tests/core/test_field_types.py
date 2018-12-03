""" Test cases for all available field type implementations"""

from datetime import datetime

import enum

import pytest

from protean.core import field
from protean.core.exceptions import ValidationError


class TestStringField:
    """ Test the String Field Implementation"""

    def test_init(self):
        """Test successful String Field initialization"""

        name = field.String(max_length=10)
        assert name is not None

    def test_type_validation(self):
        """ Test type checking validation for the Field"""
        name = field.String(max_length=10)
        assert name.load(1) == '1'

    def test_min_length(self):
        """ Test minimum length validation for the string field"""

        with pytest.raises(ValidationError):
            name = field.String(min_length=5, max_length=10)
            name.load('Dum')

    def test_max_length(self):
        """ Test maximum length validation for the string field"""

        with pytest.raises(ValidationError):
            name = field.String(max_length=5)
            name.load('Dummy Dummy')

    def test_choice(self):
        """ Test choices validations for the string field """

        class StatusChoices(enum.Enum):
            """ Set of choices for the status"""
            PENDING = 'Pending'
            SUCCESS = 'Success'
            ERROR = 'Error'

        status = field.String(max_length=10, choices=StatusChoices)
        assert status is not None

        # Test loading of values to the status field
        assert status.load('Pending') == 'Pending'
        with pytest.raises(ValidationError) as e_info:
            status.load('Failure')
        assert e_info.value.normalized_messages == {
            '_entity': ["Value `'Failure'` is not a valid choice. "
                        "Must be one of ['Pending', 'Success', 'Error']"]}


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

    def test_choice(self):
        """ Test choices validations for the Integer field """

        class StatusChoices(enum.Enum):
            """ Set of choices for the status"""
            PENDING = (0, 'Pending')
            SUCCESS = (1, 'Success')
            ERROR = (2, 'Error')

        status = field.Integer(choices=StatusChoices)
        assert status is not None

        # Test loading of values to the status field
        assert status.load(0) == 0
        with pytest.raises(ValidationError) as e_info:
            status.load(4)
        assert e_info.value.normalized_messages == {
            '_entity': ["Value `4` is not a valid choice. "
                        "Must be one of [0, 1, 2]"]}


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

    def test_choice(self):
        """ Test choices validations for the list field """

        class StatusChoices(enum.Enum):
            """ Set of choices for the status"""
            PENDING = 'Pending'
            SUCCESS = 'Success'
            ERROR = 'Error'

        status = field.List(choices=StatusChoices)
        assert status is not None

        # Test loading of values to the status field
        assert status.load(['Pending']) == ['Pending']
        with pytest.raises(ValidationError) as e_info:
            status.load(['Pending', 'Failure'])
        assert e_info.value.normalized_messages == {
            '_entity': ["Value `'Failure'` is not a valid choice. "
                        "Must be one of ['Pending', 'Success', 'Error']"]}


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


class TestDateField:
    """ Test the Date Field Implementation"""

    def test_init(self):
        """Test successful Date Field initialization"""

        age = field.Date()
        assert age is not None

        value = age.load(datetime.now().date())
        assert value == datetime.now().date()

    def test_type_casting(self):
        """ Test type casting and validation for the Field"""

        age = field.Date()

        # Test datetime being passed as value
        assert age.load(datetime.now()) == datetime.now().date()

        # Test string dates being passed as value
        expected = datetime(2018, 3, 16).date()
        assert age.load('2018-03-16') == expected
        assert age.load('2018-03-16 10:23:32') == expected
        assert age.load('16th March 2018') == expected

        # Test for invalid date
        with pytest.raises(ValidationError):
            assert age.load('15 Marchs')


class TestDateTimeField:
    """ Test the DateTime Field Implementation"""

    def test_init(self):
        """Test successful DateTime Field initialization"""

        created_at = field.DateTime()
        assert created_at is not None

        value = datetime.now()
        assert value == created_at.load(value)

    def test_type_casting(self):
        """ Test type casting and validation for the Field"""

        created_at = field.DateTime()
        today = datetime.now()
        # Test date being passed as value
        assert created_at.load(today.date()) == datetime(
            today.year, today.month, today.day)

        # Test string dates being passed as value
        assert created_at.load('2018-03-16') == datetime(2018, 3, 16)
        assert created_at.load('2018-03-16 10:23:32') == datetime(
            2018, 3, 16, 10, 23, 32)

        # Test for invalid datetime
        with pytest.raises(ValidationError):
            assert created_at.load('2018-03-16 10 23 32')


class TestTextField:
    """ Test the Text Field Implementation"""

    def test_init(self):
        """Test successful Text Field initialization"""

        address = field.Text()
        assert address is not None

    def test_type_validation(self):
        """ Test type checking validation for the Field"""
        address = field.Text()
        value = address.load('My home address')
        assert value == 'My home address'
