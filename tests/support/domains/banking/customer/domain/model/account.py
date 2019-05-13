"""Account Aggregate"""

from enum import Enum

from protean import Aggregate, ValueObject
from protean.core import field


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

    currency = field.String(max_length=3, choices=Currency)
    amount = field.Float()

    def _clone_with_values(self, **kwargs):
        # FIXME Find a way to do this generically and move method to `BaseValueObject`
        currency = kwargs.pop('currency', None)
        amount = kwargs.pop('amount', None)
        return Balance(currency=currency or self.currency,
                       amount=amount or self.amount)


@Aggregate(aggregate='account', bounded_context='customer', root=True)
class Account:
    name = field.String(max_length=50)
    account_type = field.String(
        max_length=15,
        choices=AccountType)
    balance = field.ValueObject(Balance)
