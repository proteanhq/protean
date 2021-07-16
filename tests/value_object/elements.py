from collections import defaultdict
from enum import Enum

from protean.core.aggregate import BaseAggregate
from protean.core.field.basic import Float, Identifier, Integer, String
from protean.core.field.embedded import ValueObject
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
            raise ValueError("Email address is invalid")

        return cls(address=address)

    @classmethod
    def validate(cls, address):
        """ Business rules of Email address """
        if (
            type(address) is not str
            or "@" not in address
            or address.count("@") > 1
            or len(address) > 255
        ):
            return False

        return True


class User(BaseAggregate):
    email = ValueObject(Email, required=True)
    name = String(max_length=255)


class MyOrgEmail(Email):
    pass


class Currency(Enum):
    """ Set of choices for the status"""

    USD = "USD"
    INR = "INR"
    CAD = "CAD"


class Balance(BaseValueObject):
    """A composite amount object, containing two parts:
        * currency code - a three letter unique currency code
        * amount - a float value
    """

    currency = String(max_length=3, choices=Currency)
    amount = Float()

    def clean(self):
        errors = defaultdict(list)
        if self.amount and self.amount < -1000000000000.0:
            errors["amount"].append("cannot be less than 1 Trillion")
        return errors

    def replace(self, **kwargs):
        # FIXME Find a way to do this generically and move method to `BaseValueObject`
        currency = kwargs.pop("currency", None)
        amount = kwargs.pop("amount", None)
        return Balance(currency=currency or self.currency, amount=amount or self.amount)


class Account(BaseAggregate):
    balance = ValueObject(Balance, required=True)
    kind = String(max_length=15, required=True)


class BuildingStatus(Enum):
    WIP = "WIP"
    DONE = "DONE"


class Building(BaseValueObject):
    name = String(max_length=50)
    floors = Integer()
    status = String(choices=BuildingStatus)

    def defaults(self):
        if not self.status:
            if self.floors == 4:
                self.status = BuildingStatus.DONE.value
            else:
                self.status = BuildingStatus.WIP.value

    def clean(self):
        errors = defaultdict(list)
        if self.floors >= 4 and self.status != BuildingStatus.DONE.value:
            errors["status"].append("should be DONE")
        return errors


class PolymorphicConnection(BaseValueObject):
    connected_id = Identifier(referenced_as="connected_id")
    connected_type = String(referenced_as="connected_type", max_length=15)


class PolymorphicOwner(BaseAggregate):
    connector = ValueObject(PolymorphicConnection)
