import pytest

from protean import Domain
from protean.exceptions import IncorrectUsageError
from protean.fields import Float, String, ValueObject

domain = Domain(__name__)


@domain.value_object
class Balance:
    currency = String(max_length=3, required=True)
    amount = Float(required=True)


@domain.aggregate
class Account:
    balance = ValueObject(Balance)
    name = String(max_length=30)


def test_value_objects_are_immutable():
    balance = Balance(currency="USD", amount=100.0)

    with pytest.raises(IncorrectUsageError) as exception:
        balance.currency = "INR"

    assert (
        str(exception.value)
        == "Value Objects are immutable and cannot be modified once created"
    )


def test_value_objects_can_be_switched():
    balance = Balance(currency="USD", amount=100.0)
    account = Account(balance=balance, name="John Doe")

    assert account.balance.currency == "USD"
    assert account.balance_currency == "USD"

    account.balance = Balance(currency="INR", amount=100.0)
    assert account.balance.currency == "INR"
    assert account.balance_currency == "INR"


def test_that_updating_attributes_linked_to_value_objects_has_no_impact():
    balance = Balance(currency="USD", amount=100.0)
    account = Account(balance=balance, name="John Doe")

    # This is a dummy attribute that is linked to the value object
    #   Updating this attribute should not impact the value object
    account.balance_currency = "INR"

    assert account.balance.currency == "USD"
