import pytest

from protean import BaseValueObject
from protean.exceptions import IncorrectUsageError
from protean.fields import Float, String


def test_vo_cannot_contain_fields_marked_unique():
    with pytest.raises(IncorrectUsageError) as exception:

        class Balance(BaseValueObject):
            currency = String(max_length=3, required=True, unique=True)
            amount = Float(required=True)

    assert str(exception.value) == str(
        {
            "_value_object": [
                "Value Objects cannot contain fields marked 'unique' (field 'currency')"
            ]
        }
    )


def test_vo_cannot_contain_fields_marked_as_identifiers():
    with pytest.raises(IncorrectUsageError) as exception:

        class Balance(BaseValueObject):
            currency = String(max_length=3, required=True, identifier=True)
            amount = Float(required=True)

    assert str(exception.value) == str(
        {
            "_value_object": [
                "Value Objects cannot contain fields marked 'identifier' (field 'currency')"
            ]
        }
    )
