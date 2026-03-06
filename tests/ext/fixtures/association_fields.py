"""Fixture: association field factories resolve to correct Python types."""

from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject
from protean.fields.association import HasMany, HasOne
from protean.fields.embedded import ValueObject


class Address(BaseValueObject):
    pass


class OrderItem(BaseEntity):
    pass


# HasOne(X) → X | None
ho = HasOne(OrderItem)
reveal_type(
    ho
)  # E: Revealed type is "tests.ext.fixtures.association_fields.OrderItem | None"

# HasMany(X) → list[X]
hm = HasMany(OrderItem)
reveal_type(
    hm
)  # E: Revealed type is "builtins.list[tests.ext.fixtures.association_fields.OrderItem]"

# ValueObject(X) → X | None
vo = ValueObject(Address)
reveal_type(
    vo
)  # E: Revealed type is "tests.ext.fixtures.association_fields.Address | None"
