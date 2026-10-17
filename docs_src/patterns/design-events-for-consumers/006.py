from datetime import UTC, datetime

from protean import Domain, handle
from protean.fields import (
    Auto,
    DateTime,
    Float,
    HasMany,
    Identifier,
    Integer,
    List,
    String,
)
from protean.utils.globals import current_domain

domain = Domain(name="CrossAggregateEventData")
domain.config["command_processing"] = "sync"


@domain.entity(part_of="Order")
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(min_value=1, required=True)


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    customer_name: String(required=True)
    customer_email: String(required=True)
    items: List(required=True)
    total: Float(required=True)
    placed_at: DateTime(required=True)


# --8<-- [start:place]
@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    customer_name: String(required=True)
    customer_email: String(required=True)


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    items = HasMany(OrderItem)
    status: String(default="draft")
    total: Float(default=0.0)

    def place(self, customer_name: str, customer_email: str):
        self.status = "placed"
        # Include customer data in the event -- the handler passes it in
        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                customer_id=self.customer_id,
                customer_name=customer_name,
                customer_email=customer_email,
                items=[item.to_dict() for item in self.items],
                total=self.total,
                placed_at=datetime.now(UTC),
            )
        )


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        # Command carries the cross-aggregate data
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.place(
            customer_name=command.customer_name,
            customer_email=command.customer_email,
        )
        repo.add(order)


# --8<-- [end:place]
