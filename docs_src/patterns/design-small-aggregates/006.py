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
domain.config["command_processing"] = "sync"


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


# A separate aggregate, changed only by its own command handler
@domain.aggregate
class CustomerLoyalty:
    customer_id: Identifier(identifier=True)
    points: Integer(default=0)
    applied_order_ids: List(content_type=String)

    def add_points(self, order_id, points):
        self.points += points
        self.applied_order_ids = [*self.applied_order_ids, order_id]


@domain.command(part_of=CustomerLoyalty)
class AwardPoints:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    points: Integer(required=True)


@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        current_domain.process(
            AwardPoints(
                order_id=event.order_id,
                customer_id=event.customer_id,
                points=int(event.total_amount),
            )
        )


@domain.command_handler(part_of=CustomerLoyalty)
class LoyaltyCommandHandler:
    @handle(AwardPoints)
    def award_points(self, command: AwardPoints):
        repo = current_domain.repository_for(CustomerLoyalty)
        loyalty = repo.get(command.customer_id)
        if command.order_id in loyalty.applied_order_ids:
            return  # This order was already applied
        loyalty.add_points(command.order_id, command.points)
        repo.add(loyalty)


# --8<-- [end:events]


@domain.entity(part_of=Order)
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(min_value=1, required=True)
