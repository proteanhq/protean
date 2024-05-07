import pytest

from protean import BaseValueObject, Domain
from protean.exceptions import IncorrectUsageError
from protean.fields import Float, String
from protean.reflection import id_field

domain = Domain(__name__)


class Balance(BaseValueObject):
    currency = String(max_length=3, required=True)
    amount = Float(required=True)


def test_value_objects_do_not_have_id_fields():
    with pytest.raises(IncorrectUsageError) as exception:
        id_field(Balance)

    assert str(exception.value) == str(
        {
            "identity": [
                "<class 'tests.reflection.test_id_field.Balance'> does not have identity fields"
            ]
        }
    )
