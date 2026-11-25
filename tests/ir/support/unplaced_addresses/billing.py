"""An ``Address`` value object that only a projection holds."""

from protean.core.projection import BaseProjection
from protean.core.value_object import BaseValueObject
from protean.fields import Identifier, String, ValueObject


class Address(BaseValueObject):
    street = String()


class BillingCard(BaseProjection):
    customer_id = Identifier(identifier=True)
    address = ValueObject(Address)
