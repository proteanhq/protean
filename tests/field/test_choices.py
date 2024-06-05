import pytest

from enum import Enum

from protean.exceptions import ValidationError
from protean.fields import String


def test_choices_as_enum():
    """Test choices validations for the string field"""

    class StatusChoices(Enum):
        """Set of choices for the status"""

        PENDING = "Pending"
        SUCCESS = "Success"
        ERROR = "Error"

    status = String(max_length=10, choices=StatusChoices)
    assert status is not None

    # Test loading a value
    assert status._load("Pending") == "Pending"
    # Test loading an Enum
    assert status._load(StatusChoices.PENDING) == "Pending"

    # Test invalid value
    with pytest.raises(ValidationError) as e_info:
        status._load("Failure")

    assert e_info.value.messages == {
        "unlinked": [
            "Value `'Failure'` is not a valid choice. "
            "Must be among ['Pending', 'Success', 'Error']"
        ]
    }


def test_choices_as_list():
    """Test choices validations for the string field"""

    status = String(max_length=10, choices=["Pending", "Success", "Error"])
    assert status is not None

    # Test loading a value
    assert status._load("Pending") == "Pending"

    # Test invalid value
    with pytest.raises(ValidationError) as e_info:
        status._load("Failure")

    assert e_info.value.messages == {
        "unlinked": [
            "Value `'Failure'` is not a valid choice. "
            "Must be among ['Pending', 'Success', 'Error']"
        ]
    }
