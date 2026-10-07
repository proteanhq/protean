from protean import Domain, handle
from protean.exceptions import ValidationError
from protean.fields import (
    Auto,
    Float,
    HasMany,
    Identifier,
    Integer,
    List,
    String,
    ValueObject,
)
from protean.utils.globals import current_domain

domain = Domain(name="SmallAggregatesEvents")
domain.config["event_processing"] = "sync"


@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, required=True)


# --8<-- [start:events]
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total_amount: Float(required=True)
    items: List(required=True)  # Each item: product_id, quantity


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    items = HasMany("OrderItem")
    status: String(default="draft")
    total = ValueObject(Money)

    def place(self):
        if self.status != "draft":
            raise ValidationError({"status": ["Only draft orders can be placed"]})

        self.status = "placed"
        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                customer_id=self.customer_id,
                total_amount=self.total.amount,
                items=[
                    {"product_id": item.product_id, "quantity": item.quantity}
                    for item in self.items
                ],
            )
        )


# A separate aggregate, with its own event handler
@domain.aggregate
class CustomerLoyalty:
    customer_id: Identifier(identifier=True)
    points: Integer(default=0)

    def add_points(self, points):
        self.points += points


@domain.event_handler(
    part_of=CustomerLoyalty, stream_category=Order.meta_.stream_category
)
class CustomerLoyaltyEventHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(CustomerLoyalty)
        loyalty = repo.get(event.customer_id)
        loyalty.add_points(int(event.total_amount))
        repo.add(loyalty)


# --8<-- [end:events]


@domain.entity(part_of=Order)
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(min_value=1, required=True)
