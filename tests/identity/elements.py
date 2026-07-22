from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.fields import Auto, HasMany, Integer, String


class Person(BaseAggregate):
    first_name: String(max_length=50, required=True)
    last_name: String(max_length=50, required=True)
    age: Integer(default=21)


class LineItem(BaseEntity):
    product: String(max_length=50, required=True)
    quantity: Integer(default=1)


class Order(BaseAggregate):
    number: String(max_length=20)
    items = HasMany(LineItem)


class ExplicitIdentity(BaseAggregate):
    """Declares its own identifier, to check the explicit and auto-injected
    identity paths agree under ``identity_type = "uuid"``."""

    ref: Auto(identifier=True, identity_type="uuid")
    name: String(max_length=50)
