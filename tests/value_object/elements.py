from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import Field, field_validator

from protean import invariant
from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import String, ValueObject


class Email(BaseValueObject):
    """An email address value object, with two clearly identified parts:
    * local_part
    * domain_part
    """

    # This is the external facing data attribute
    address: Annotated[str, Field(max_length=254)]

    @classmethod
    def from_address(cls, address):
        """Construct an Email VO from an email address.

        email = Email.from_address('john.doe@gmail.com')

        """
        if not cls.validate(address):
            raise ValueError("Email address is invalid")

        return cls(address=address)

    @classmethod
    def validate(cls, address):
        """Business rules of Email address"""
        if (
            not isinstance(address, str)
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
    """Set of choices for the status"""

    USD = "USD"
    INR = "INR"
    CAD = "CAD"


class Balance(BaseValueObject):
    """A composite amount object, containing two parts:
    * currency code - a three letter unique currency code
    * amount - a float value
    """

    currency: Annotated[str, Field(max_length=3)] | None = None
    amount: float | None = None

    @field_validator("currency")
    @classmethod
    def validate_currency_choices(cls, v: str | None) -> str | None:
        if v is not None:
            valid = {c.value for c in Currency}
            if v not in valid:
                raise ValueError(
                    f"Value '{v}' is not a valid choice. "
                    f"Valid choices are: {sorted(valid)}"
                )
        return v

    @invariant.post
    def validate_balance_cannot_be_less_than_1_trillion(self):
        """Business rules of Balance"""
        if self.amount and self.amount < -1000000000000.0:
            raise ValidationError({"amount": ["cannot be less than 1 Trillion"]})

    def replace(self, **kwargs):
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
    name: Annotated[str, Field(max_length=50)] | None = None
    floors: int | None = None
    status: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status_choices(cls, v: str | None) -> str | None:
        if v is not None:
            valid = {c.value for c in BuildingStatus}
            if v not in valid:
                raise ValueError(
                    f"Value '{v}' is not a valid choice. "
                    f"Valid choices are: {sorted(valid)}"
                )
        return v

    def defaults(self):
        if not self.status:
            if self.floors == 4:
                self.status = BuildingStatus.DONE.value
            else:
                self.status = BuildingStatus.WIP.value

    @invariant.post
    def check_building_status_based_on_floors(self):
        if (
            self.floors is not None
            and self.floors >= 4
            and self.status != BuildingStatus.DONE.value
        ):
            raise ValidationError({"status": ["should be DONE"]})


class PolymorphicConnection(BaseValueObject):
    connected_id: str | None = Field(
        default=None, json_schema_extra={"referenced_as": "connected_id"}
    )
    connected_type: Annotated[str, Field(max_length=15)] | None = Field(
        default=None, json_schema_extra={"referenced_as": "connected_type"}
    )


class PolymorphicOwner(BaseAggregate):
    connector = ValueObject(PolymorphicConnection)
