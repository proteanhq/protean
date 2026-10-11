from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import HasMany, Identifier, Integer, String

domain = Domain()


# --8<-- [start:always_valid]
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    status: String(max_length=20, default="draft")
    items = HasMany("OrderItem")

    @invariant.post
    def must_have_items_when_placed(self):
        if self.status != "draft" and not self.items:
            raise ValidationError({"items": ["Order must have at least one item"]})


@domain.entity(part_of=Order)
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(min_value=1, default=1)


# --8<-- [end:always_valid]
