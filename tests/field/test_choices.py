"""Test choice validation through domain objects."""

from enum import Enum

import pytest

from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import String


def test_choices_as_enum():
    """Test choices validations for the string field with Enum"""

    class StatusChoices(Enum):
        """Set of choices for the status"""

        PENDING = "Pending"
        SUCCESS = "Success"
        ERROR = "Error"

    class StatusVO(BaseValueObject):
        status: String(max_length=10, choices=StatusChoices)

    # Test loading a valid value
    vo = StatusVO(status="Pending")
    assert vo.status == "Pending"

    # Test invalid value
    with pytest.raises(ValidationError):
        StatusVO(status="Failure")


def test_choices_as_list():
    """Test choices validations for the string field with list"""

    class StatusVO(BaseValueObject):
        status: String(max_length=10, choices=["Pending", "Success", "Error"])

    # Test loading a valid value
    vo = StatusVO(status="Pending")
    assert vo.status == "Pending"

    # Test invalid value
    with pytest.raises(ValidationError):
        StatusVO(status="Failure")
