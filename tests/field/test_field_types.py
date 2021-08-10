""" Test cases for all available field type implementations"""

import enum

from datetime import datetime

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.field.basic import (
    Auto,
    Boolean,
    Date,
    DateTime,
    Dict,
    Float,
    Integer,
    List,
    String,
    Text,
)
from protean.exceptions import ValidationError


class TestStringField:
    """ Test the String Field Implementation"""

    def test_init(self):
        """Test successful String Field initialization"""

        name = String(max_length=10)
        assert name is not None

    def test_type_validation(self):
        """ Test type checking validation for the Field"""
        name = String(max_length=10)
        assert name._load(1) == "1"

    def test_min_length(self):
        """ Test minimum length validation for the string field"""

        with pytest.raises(ValidationError):
            name = String(min_length=5, max_length=10)
            name._load("Dum")

    def test_max_length(self):
        """ Test maximum length validation for the string field"""

        with pytest.raises(ValidationError):
            name = String(max_length=5)
            name._load("Dummy Dummy")

    def test_choice(self):
        """ Test choices validations for the string field """

        class StatusChoices(enum.Enum):
            """ Set of choices for the status"""

            PENDING = "Pending"
            SUCCESS = "Success"
            ERROR = "Error"

        status = String(max_length=10, choices=StatusChoices)
        assert status is not None

        # Test loading of values to the status field
        assert status._load("Pending") == "Pending"
        with pytest.raises(ValidationError) as e_info:
            status._load("Failure")
        assert e_info.value.messages == {
            "unlinked": [
                "Value `'Failure'` is not a valid choice. "
                "Must be among ['Pending', 'Success', 'Error']"
            ]
        }


class TestIntegerField:
    """ Test the Integer Field Implementation"""

    def test_init(self):
        """Test successful Integer Field initialization"""

        age = Integer()
        assert age is not None

    def test_various_input_values(self):
        age = Integer()
        assert age._load(12) == 12
        assert age._load("12") == 12
        assert age._load(None) is None
        assert age._load("") is None

    def test_type_validation(self):
        """ Test type checking validation for the Field"""
        with pytest.raises(ValidationError):
            age = Integer()
            age._load("x")

    def test_min_value(self):
        """ Test minimum value validation for the integer field"""

        with pytest.raises(ValidationError):
            age = Integer(min_value=5)
            age._load(3)

    def test_max_value(self):
        """ Test maximum value validation for the integer field"""

        with pytest.raises(ValidationError):
            age = Integer(max_value=5)
            age._load(6)

    def test_choice(self):
        """ Test choices validations for the Integer field """

        class StatusChoices(enum.Enum):
            """ Set of choices for the status"""

            PENDING = (0, "Pending")
            SUCCESS = (1, "Success")
            ERROR = (2, "Error")

        status = Integer(choices=StatusChoices)
        assert status is not None

        # Test loading of values to the status field
        assert status._load(0) == 0
        with pytest.raises(ValidationError) as e_info:
            status._load(4)
        assert e_info.value.messages == {
            "unlinked": ["Value `4` is not a valid choice. " "Must be among [0, 1, 2]"]
        }


class TestFloatField:
    """ Test the Float Field Implementation"""

    def test_init(self):
        """Test successful Float Field initialization"""

        score = Float()
        assert score is not None

    def test_type_validation(self):
        """ Test type checking validation for the Field"""
        with pytest.raises(ValidationError):
            score = Float()
            score._load("x")

    def test_min_value(self):
        """ Test minimum value validation for the float field"""

        with pytest.raises(ValidationError):
            score = Float(min_value=5.4)
            score._load(5.3)

    def test_max_value(self):
        """ Test maximum value validation for the float field"""

        with pytest.raises(ValidationError):
            score = Float(max_value=5.5)
            score._load(5.6)

    @pytest.mark.xfail
    def test_none_value(self):
        """ Test None value treatment for the float field"""

        score = Float(max_value=5.5)
        score._load(None)

        assert score.value == 0.0


class TestBooleanField:
    """ Test the Boolean Field Implementation"""

    def test_init(self):
        """Test successful Boolean Field initialization"""

        married = Boolean()
        assert married is not None
        assert married._load(True) is True

    def test_type_validation(self):
        """ Test type checking validation for the Field"""
        with pytest.raises(ValidationError):
            married = Boolean()
            married._load("x")

    def test_default_value(self):
        """Test that Boolean fields accept default values properly"""

        class Youth(BaseAggregate):
            name = String(max_length=50)
            married = Boolean(default=False)

        class Adult(BaseAggregate):
            name = String(max_length=50)
            married = Boolean(default=True)

        youth = Youth(name="Baby Doe")
        adult = Adult(name="John Doe")

        assert youth.married is False
        assert adult.married is True


class TestListField:
    """ Test the List Field Implementation"""

    def test_init(self):
        """Test successful List Field initialization"""

        tags = List()
        assert tags is not None

        assert tags._load(["x", "y", "z"]) == ["x", "y", "z"]

    def test_type_validation(self):
        """ Test type checking validation for the Field"""
        numbers = List(content_type=Integer)
        with pytest.raises(ValidationError):
            numbers._load("x")

    def test_choice(self):
        """ Test choices validations for the list field """

        class StatusChoices(enum.Enum):
            """ Set of choices for the status"""

            PENDING = "Pending"
            SUCCESS = "Success"
            ERROR = "Error"

        status = List(choices=StatusChoices)
        assert status is not None

        # Test loading of values to the status field
        assert status._load(["Pending"]) == ["Pending"]
        with pytest.raises(ValidationError) as e_info:
            status._load(["Pending", "Failure"])
        assert e_info.value.messages == {
            "unlinked": [
                "Value `'Failure'` is not a valid choice. "
                "Must be among ['Pending', 'Success', 'Error']"
            ]
        }


class TestDictField:
    """ Test the Dict Field Implementation"""

    def test_init(self):
        """Test successful Dict Field initialization"""

        add_info = Dict()
        assert add_info is not None

        value = add_info._load({"available": "weekdays"})
        assert value == {"available": "weekdays"}

    def test_type_validation(self):
        """ Test type checking validation for the Field"""
        with pytest.raises(ValidationError):
            add_info = Dict()
            add_info._load("x")


class TestAutoField:
    """ Test the Auto Field Implementation"""

    def test_init(self):
        """Test successful Dict Field initialization"""

        add_info = Auto()
        assert add_info is not None

        value = add_info._load(1)
        assert value == 1

    def test_that_auto_fields_that_are_identifiers_are_also_unique(self):
        message_id = Auto(identifier=True)
        assert message_id.identifier is True
        assert message_id.unique is True

    def test_validation(self):
        """ Test validation for the Auto Field"""
        add_info = Auto(required=True)
        add_info._load(None)


class TestDateField:
    """ Test the Date Field Implementation"""

    def test_init(self):
        """Test successful Date Field initialization"""

        age = Date()
        assert age is not None

        value = age._load(datetime.now().date())
        assert value == datetime.now().date()

    def test_type_casting(self):
        """ Test type casting and validation for the Field"""

        age = Date()

        # Test datetime being passed as value
        assert age._load(datetime.now()) == datetime.now().date()

        # Test string dates being passed as value
        expected = datetime(2018, 3, 16).date()
        assert age._load("2018-03-16") == expected
        assert age._load("2018-03-16 10:23:32") == expected
        assert age._load("16th March 2018") == expected

        # Test for invalid date
        with pytest.raises(ValidationError):
            assert age._load("15 Marchs")


class TestDateTimeField:
    """ Test the DateTime Field Implementation"""

    def test_init(self):
        """Test successful DateTime Field initialization"""

        created_at = DateTime()
        assert created_at is not None

        value = datetime.now()
        assert value == created_at._load(value)

    def test_type_casting(self):
        """ Test type casting and validation for the Field"""

        created_at = DateTime()
        today = datetime.now()
        # Test date being passed as value
        assert created_at._load(today.date()) == datetime(
            today.year, today.month, today.day
        )

        # Test string dates being passed as value
        assert created_at._load("2018-03-16") == datetime(2018, 3, 16)
        assert created_at._load("2018-03-16 10:23:32") == datetime(
            2018, 3, 16, 10, 23, 32
        )

        # Test for invalid datetime
        with pytest.raises(ValidationError):
            assert created_at._load("2018-03-16 10 23 32")


class TestTextField:
    """ Test the Text Field Implementation"""

    def test_init(self):
        """Test successful Text Field initialization"""

        address = Text()
        assert address is not None

    def test_type_validation(self):
        """ Test type checking validation for the Field"""
        address = Text()
        value = address._load("My home address")
        assert value == "My home address"
