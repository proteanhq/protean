"""A second ``Address`` value object, in another module, that only a
projection holds."""

from protean.core.projection import BaseProjection
from protean.core.value_object import BaseValueObject
from protean.fields import Identifier, String, ValueObject


class Address(BaseValueObject):
    city = String()


class ShippingCard(BaseProjection):
    customer_id = Identifier(identifier=True)
    address = ValueObject(Address)
