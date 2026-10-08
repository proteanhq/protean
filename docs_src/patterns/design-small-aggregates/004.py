from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Auto, Float, HasMany, Identifier, Integer, String

domain = Domain(name="SmallAggregatesEntities")


# --8<-- [start:entities]
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    items = HasMany("OrderItem")
    status: String(default="draft")

    def add_item(self, product_id, product_name, quantity, unit_price):
        item = OrderItem(
            product_id=product_id,
            product_name=product_name,
            quantity=quantity,
            unit_price=unit_price,
        )
        self.add_items(item)

    @invariant.post
    def order_must_have_items(self):
        if self.status != "draft" and not self.items:
            raise ValidationError({"items": ["Order must have at least one item"]})


@domain.entity(part_of=Order)
class OrderItem:
    product_id: Identifier(required=True)
    product_name: String(required=True)
    quantity: Integer(min_value=1, required=True)
    unit_price: Float(required=True)


# --8<-- [end:entities]
