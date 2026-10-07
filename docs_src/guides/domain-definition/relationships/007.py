from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import HasMany, String

domain = Domain(name="Ordering")


# --8<-- [start:aggregate]
@domain.aggregate
class Order:
    items = HasMany("OrderItem")

    @invariant.post
    def must_have_at_least_one_item(self):
        if not self.items:
            raise ValidationError({"items": ["Order must have at least one item"]})


@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(max_length=100)


# --8<-- [end:aggregate]
