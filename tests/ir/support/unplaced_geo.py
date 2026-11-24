"""A ``ShippingAddress`` value object that holds a ``Geo`` value object, with
only a projection holding the address."""

from protean.core.projection import BaseProjection
from protean.core.value_object import BaseValueObject
from protean.fields import Float, Identifier, String, ValueObject


class Geo(BaseValueObject):
    lat = Float()


class ShippingAddress(BaseValueObject):
    city = String()
    geo = ValueObject(Geo)


class CustomerCard(BaseProjection):
    customer_id = Identifier(identifier=True)
    address = ValueObject(ShippingAddress)
