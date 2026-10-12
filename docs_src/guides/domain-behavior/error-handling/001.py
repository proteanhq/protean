from protean import Domain, invariant
from protean.fields import Float, HasMany, Identifier, Integer, String

domain = Domain()


# --8<-- [start:invariant]
from protean.exceptions import ValidationError


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    items = HasMany("OrderItem")
    status = String(default="draft")

    @invariant.post
    def must_have_items(self):
        if not self.items:
            raise ValidationError({"_entity": ["Order must contain at least one item"]})


@domain.entity(part_of=Order)
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(min_value=1, default=1)
    price: Float(min_value=0.0, default=0.0)


# --8<-- [end:invariant]
