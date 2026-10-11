from protean import Domain
from protean.fields import HasMany, Identifier, Integer, String

domain = Domain()


# --8<-- [start:raise_event]
@domain.aggregate
class Order:
    number: String(max_length=20)
    items = HasMany("OrderItem")


@domain.event(part_of=Order)
class OrderItemQuantityChanged:
    order_id: Identifier(required=True)
    product_name: String(max_length=100)
    new_quantity: Integer()


@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(max_length=100)
    quantity: Integer()

    def update_quantity(self, new_qty):
        self.quantity = new_qty
        self.raise_(
            OrderItemQuantityChanged(
                order_id=str(self._owner.id),
                product_name=self.product_name,
                new_quantity=new_qty,
            )
        )


# --8<-- [end:raise_event]
