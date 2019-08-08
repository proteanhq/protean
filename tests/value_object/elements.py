# Standard Library Imports
from enum import Enum

# Protean
from protean.core.aggregate import BaseAggregate
from protean.core.exceptions import ValidationError
from protean.core.field.basic import Float, String
from protean.core.field.embedded import ValueObjectField
from protean.core.value_object import BaseValueObject


class Email(BaseValueObject):
    """An email address value object, with two clearly identified parts:
        * local_part
        * domain_part
    """

    # This is the external facing data attribute
    address = String(max_length=254, required=True)

    @classmethod
    def from_address(cls, address):
        """ Construct an Email VO from an email address.

        email = Email.from_address('john.doe@gmail.com')

        """
        if not cls.validate(address):
            raise ValueError('Email address is invalid')

        return cls(address=address)

    @classmethod
    def validate(cls, address):
        """ Business rules of Email address """
        if (type(address) is not str or
                '@' not in address or
                address.count('@') > 1 or
                len(address) > 255):
            return False

        return True


class User(BaseAggregate):
    email = ValueObjectField(Email, required=True)
    name = String(max_length=255)


class MyOrgEmail(Email):
    pass


class Currency(Enum):
    """ Set of choices for the status"""
    USD = 'USD'
    INR = 'INR'
    CAD = 'CAD'


class Balance(BaseValueObject):
    """A composite amount object, containing two parts:
        * currency code - a three letter unique currency code
        * amount - a float value
    """

    currency = String(max_length=3, choices=Currency)
    amount = Float()

    def clean(self):
        if self.amount and self.amount < -1000000000000.0:
            raise ValidationError("Amount cannot be less than 1 Trillion")

    def replace(self, **kwargs):
        # FIXME Find a way to do this generically and move method to `BaseValueObject`
        currency = kwargs.pop('currency', None)
        amount = kwargs.pop('amount', None)
        return Balance(currency=currency or self.currency,
                       amount=amount or self.amount)


class Account(BaseAggregate):
    balance = ValueObjectField(Balance, required=True)
    kind = String(max_length=15, required=True)
