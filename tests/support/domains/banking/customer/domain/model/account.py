"""Account Aggregate"""

from enum import Enum

from protean import Aggregate, ValueObject
from protean.core.field.basic import String, Float
from protean.core.field.embedded import ValueObjectField


class Currency(Enum):
    """ Set of choices for the status"""
    USD = 'USD'
    INR = 'INR'
    CAD = 'CAD'


class AccountType(Enum):
    SAVINGS = 'SAVINGS'
    CHECKING = 'CHECKING'


@ValueObject(aggregate='account', bounded_context='customer')
class Balance:
    """A composite amount object, containing two parts:
        * currency code - a three letter unique currency code
        * amount - a float value
    """

    currency = String(max_length=3, choices=Currency)
    amount = Float()

    def _clone_with_values(self, **kwargs):
        # FIXME Find a way to do this generically and move method to `BaseValueObject`
        currency = kwargs.pop('currency', None)
        amount = kwargs.pop('amount', None)
        return Balance(currency=currency or self.currency,
                       amount=amount or self.amount)


@Aggregate(aggregate='account', bounded_context='customer')
class Account:
    name = String(max_length=50)
    account_type = String(
        max_length=15,
        choices=AccountType)
    balance = ValueObjectField(Balance)
