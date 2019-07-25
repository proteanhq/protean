# Standard Library Imports
from enum import Enum

# Protean
from protean.core.exceptions import ValidationError
from protean.core.field.basic import Float, String
from protean.core.value_object import BaseValueObject


class Email(BaseValueObject):
    """An email address value object, with two clearly identified parts:
        * local_part
        * domain_part
    """

    # This is the external facing data attribute
    address = String(max_length=254)

    def __init__(self, *template, local_part=None, domain_part=None, **kwargs):
        super(Email, self).__init__(*template, **kwargs)

        # `local_part` and `domain_part` are internal attributes that capture
        #   and preserve the validity of an Email Address
        self.local_part = local_part
        self.domain_part = domain_part

        if self.local_part and self.domain_part:
            self.address = '@'.join([self.local_part, self.domain_part])
        else:
            raise ValidationError("`local_part` and `domain_part` of email address are mandatory")

    @classmethod
    def from_address(cls, address):
        if not cls.validate(address):
            raise ValueError('Email address is invalid')

        local_part, _, domain_part = address.partition('@')

        return cls(local_part=local_part, domain_part=domain_part)

    @classmethod
    def from_parts(cls, local_part, domain_part):
        return cls(local_part=local_part, domain_part=domain_part)

    @classmethod
    def validate(cls, address):
        if type(address) is not str:
            return False
        if '@' not in address:
            return False
        if len(address) > 255:
            return False

        return True


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
        if self.amount < -1000000000000.0:
            raise ValidationError("Amount cannot be less than 1 Trillion")

    def replace(self, **kwargs):
        # FIXME Find a way to do this generically and move method to `BaseValueObject`
        currency = kwargs.pop('currency', None)
        amount = kwargs.pop('amount', None)
        return Balance(currency=currency or self.currency,
                       amount=amount or self.amount)
