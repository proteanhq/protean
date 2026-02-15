"""Test cases for all available field type implementations.

Tests validate field behavior through domain objects (VOs and aggregates)
since FieldSpec objects are configuration carriers — validation happens
at the model level when a domain object is instantiated.
"""

import enum
from datetime import datetime

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import (
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


class TestStringField:
    """Test the String Field Implementation"""

    def test_init(self):
        """Test successful String Field initialization"""
        name = String(max_length=10)
        assert name is not None

    def test_returns_none_as_it_is(self):
        class VO(BaseValueObject):
            name = String(max_length=10)

        vo = VO(name=None)
        assert vo.name is None

    def test_type_validation(self):
        """Test type checking: non-string values are rejected"""

        class VO(BaseValueObject):
            name = String(max_length=10)

        with pytest.raises(ValidationError):
            VO(name=1)

    def test_float_rejected_by_string_field(self):
        """Passing a float to a String field raises ValidationError.

        Regression: Pydantic v2 enforces strict type checking for string
        fields.  A String(max_length=10) field will not silently coerce
        a float like 999.99 into "999.99".
        """

        class VO(BaseValueObject):
            price = String(max_length=10)

        with pytest.raises(ValidationError) as exc:
            VO(price=999.99)

        assert "price" in exc.value.messages

    def test_min_length(self):
        """Test minimum length validation for the string field"""

        class VO(BaseValueObject):
            name = String(min_length=5, max_length=10)

        with pytest.raises(ValidationError):
            VO(name="Dum")

    def test_max_length(self):
        """Test maximum length validation for the string field"""

        class VO(BaseValueObject):
            name = String(max_length=5)

        with pytest.raises(ValidationError):
            VO(name="Dummy Dummy")

    def test_choice(self):
        """Test choices validations for the string field"""

        class StatusChoices(enum.Enum):
            """Set of choices for the status"""

            PENDING = "Pending"
            SUCCESS = "Success"
            ERROR = "Error"

        class VO(BaseValueObject):
            status = String(max_length=10, choices=StatusChoices)

        # Test valid choice
        vo = VO(status="Pending")
        assert vo.status == "Pending"

        # Test invalid choice
        with pytest.raises(ValidationError):
            VO(status="Failure")


class TestIntegerField:
    """Test the Integer Field Implementation"""

    def test_init(self):
        """Test successful Integer Field initialization"""
        age = Integer()
        assert age is not None

    def test_various_input_values(self):
        class VO(BaseValueObject):
            age = Integer()

        vo = VO(age=12)
        assert vo.age == 12

        # String integers are coerced
        vo = VO(age="12")
        assert vo.age == 12

        # None is allowed for optional fields
        vo = VO(age=None)
        assert vo.age is None

    def test_type_validation(self):
        """Test type checking validation for the Field"""

        class VO(BaseValueObject):
            age = Integer()

        with pytest.raises(ValidationError):
            VO(age="x")

    def test_min_value(self):
        """Test minimum value validation for the integer field"""

        class VO(BaseValueObject):
            age = Integer(min_value=5)

        with pytest.raises(ValidationError):
            VO(age=3)

    def test_max_value(self):
        """Test maximum value validation for the integer field"""

        class VO(BaseValueObject):
            age = Integer(max_value=5)

        with pytest.raises(ValidationError):
            VO(age=6)

    def test_choice(self):
        """Test choices validations for the Integer field"""

        class StatusChoices(enum.Enum):
            """Set of choices for the status"""

            PENDING = 0
            SUCCESS = 1
            ERROR = 2

        class VO(BaseValueObject):
            status = Integer(choices=StatusChoices)

        # Test valid choice
        vo = VO(status=0)
        assert vo.status == 0

        # Test invalid choice
        with pytest.raises(ValidationError):
            VO(status=4)


class TestFloatField:
    """Test the Float Field Implementation"""

    def test_init(self):
        """Test successful Float Field initialization"""
        score = Float()
        assert score is not None

    def test_type_validation(self):
        """Test type checking validation for the Field"""

        class VO(BaseValueObject):
            score = Float()

        with pytest.raises(ValidationError):
            VO(score="x")

    def test_min_value(self):
        """Test minimum value validation for the float field"""

        class VO(BaseValueObject):
            score = Float(min_value=5.4)

        with pytest.raises(ValidationError):
            VO(score=5.3)

    def test_max_value(self):
        """Test maximum value validation for the float field"""

        class VO(BaseValueObject):
            score = Float(max_value=5.5)

        with pytest.raises(ValidationError):
            VO(score=5.6)

    def test_min_value_error_message_format(self):
        """min_value constraint produces Pydantic v2 'ge' error message.

        Regression: FieldSpec translates min_value to Pydantic's ge constraint,
        so the error message follows Pydantic's format, not the legacy
        'value is lesser than' format.
        """

        class VO(BaseValueObject):
            percentage = Float(min_value=0.0)

        with pytest.raises(ValidationError) as exc:
            VO(percentage=-10.0)

        assert "Input should be greater than or equal to 0" in str(exc.value)

    def test_max_value_error_message_format(self):
        """max_value constraint produces Pydantic v2 'le' error message.

        Regression: FieldSpec translates max_value to Pydantic's le constraint,
        so the error message follows Pydantic's format, not the legacy
        'value is greater than' format.
        """

        class VO(BaseValueObject):
            percentage = Float(max_value=100.0)

        with pytest.raises(ValidationError) as exc:
            VO(percentage=150.0)

        assert "Input should be less than or equal to 100" in str(exc.value)


class TestBooleanField:
    """Test the Boolean Field Implementation"""

    def test_init(self):
        """Test successful Boolean Field initialization"""

        class VO(BaseValueObject):
            married = Boolean()

        vo = VO(married=True)
        assert vo.married is True

    def test_type_validation(self):
        """Test type checking validation for the Field"""

        class VO(BaseValueObject):
            married = Boolean()

        with pytest.raises(ValidationError):
            VO(married="x")

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
    """Test the List Field Implementation"""

    def test_init(self):
        """Test successful List Field initialization"""

        class VO(BaseValueObject):
            tags = List()

        vo = VO(tags=["x", "y", "z"])
        assert vo.tags == ["x", "y", "z"]

    def test_type_validation(self):
        """Test type checking validation for the Field"""

        class VO(BaseValueObject):
            numbers = List(content_type=Integer)

        with pytest.raises(ValidationError):
            VO(numbers="x")

    def test_choice(self):
        """Test choices validations for the list field.

        Choices on list elements are
        expressed via content_type with choices.
        """

        class StatusChoices(enum.Enum):
            """Set of choices for the status"""

            PENDING = "Pending"
            SUCCESS = "Success"
            ERROR = "Error"

        class VO(BaseValueObject):
            status = List(content_type=String(max_length=10, choices=StatusChoices))

        # Test valid choice values
        vo = VO(status=["Pending"])
        assert vo.status == ["Pending"]

        # Test invalid choice value
        with pytest.raises(ValidationError):
            VO(status=["Pending", "Failure"])


class TestDictField:
    """Test the Dict Field Implementation"""

    def test_init(self):
        """Test successful Dict Field initialization"""

        class VO(BaseValueObject):
            add_info = Dict()

        vo = VO(add_info={"available": "weekdays"})
        assert vo.add_info == {"available": "weekdays"}

    def test_type_validation(self):
        """Test type checking validation for the Field"""

        class VO(BaseValueObject):
            add_info = Dict()

        with pytest.raises(ValidationError):
            VO(add_info="x")


class TestAutoField:
    """Test the Auto Field Implementation"""

    def test_init(self):
        """Test successful Auto Field initialization"""
        add_info = Auto()
        assert add_info is not None

    def test_that_auto_fields_that_are_identifiers_are_set_correctly(self):
        """Test that Auto fields with identifier=True store the identifier flag"""
        message_id = Auto(identifier=True)
        assert message_id.identifier is True

    def test_auto_field_metadata(self):
        """Test Auto field stores increment and identity metadata"""
        auto_field = Auto(increment=True)
        assert auto_field._increment is True


class TestDateField:
    """Test the Date Field Implementation"""

    def test_init(self):
        """Test successful Date Field initialization"""

        class VO(BaseValueObject):
            birthday = Date()

        vo = VO(birthday=datetime.now().date())
        assert vo.birthday == datetime.now().date()

    def test_type_casting(self):
        """Test type casting and validation for the Field"""

        class VO(BaseValueObject):
            birthday = Date()

        # Test string dates being passed as value
        expected = datetime(2018, 3, 16).date()
        vo = VO(birthday="2018-03-16")
        assert vo.birthday == expected

        # Test for invalid date
        with pytest.raises(ValidationError):
            VO(birthday="15 Marchs")

    def test_null_values(self):
        class VO(BaseValueObject):
            birthday = Date()

        vo = VO(birthday=None)
        assert vo.birthday is None


class TestDateTimeField:
    """Test the DateTime Field Implementation"""

    def test_init(self):
        """Test successful DateTime Field initialization"""

        class VO(BaseValueObject):
            created_at = DateTime()

        value = datetime.now()
        vo = VO(created_at=value)
        assert vo.created_at == value

    def test_type_casting(self):
        """Test type casting and validation for the Field"""

        class VO(BaseValueObject):
            created_at = DateTime()

        # Test string dates being passed as value
        vo = VO(created_at="2018-03-16")
        assert vo.created_at == datetime(2018, 3, 16)

        vo = VO(created_at="2018-03-16T10:23:32")
        assert vo.created_at == datetime(2018, 3, 16, 10, 23, 32)

    def test_null_values(self):
        class VO(BaseValueObject):
            created_at = DateTime()

        vo = VO(created_at=None)
        assert vo.created_at is None


class TestTextField:
    """Test the Text Field Implementation"""

    def test_init(self):
        """Test successful Text Field initialization"""
        address = Text()
        assert address is not None

    def test_type_validation(self):
        """Test type checking validation for the Field"""

        class VO(BaseValueObject):
            address = Text()

        vo = VO(address="My home address")
        assert vo.address == "My home address"
