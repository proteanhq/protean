from protean import Domain, current_domain, handle
from protean.fields import Dict, Float, Identifier, Integer, List, String

domain = Domain(name="OneAggregatePerTransactionFulfillment")
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    customer_id: Identifier(required=True)
    items: List(content_type=Dict)
    total: Float(default=0.0)
    status: String(max_length=20, default="new")

    def place(self):
        self.status = "placed"
        self.total = sum(item["price"] * item["quantity"] for item in self.items)
        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                customer_id=self.customer_id,
                items=self.items,
                total=self.total,
            )
        )


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(required=True)
    total: Float(required=True)


@domain.command(part_of=Order)
class PlaceOrder:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(required=True)


@domain.aggregate
class Inventory:
    product_id: Identifier(identifier=True)
    available: Integer(default=0)
    reserved: Integer(default=0)
    applied_order_ids: List(content_type=String)

    def reserve(self, order_id, quantity):
        self.available -= quantity
        self.reserved += quantity
        self.applied_order_ids = [*self.applied_order_ids, order_id]


@domain.command(part_of=Inventory)
class ReserveStock:
    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)


@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(ReserveStock)
    def reserve_stock(self, command: ReserveStock):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.get(command.product_id)
        if command.order_id in inventory.applied_order_ids:
            return
        inventory.reserve(command.order_id, command.quantity)
        repo.add(inventory)


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


@domain.command_handler(part_of=CustomerLoyalty)
class LoyaltyCommandHandler:
    @handle(AwardPoints)
    def award_points(self, command: AwardPoints):
        repo = current_domain.repository_for(CustomerLoyalty)
        loyalty = repo.get(command.customer_id)
        if command.order_id in loyalty.applied_order_ids:
            return
        loyalty.add_points(command.order_id, command.points)
        repo.add(loyalty)


@domain.aggregate
class Notification:
    notification_id: Identifier(identifier=True)
    recipient_id: Identifier(required=True)
    template: String(max_length=50, required=True)
    data: Dict()


@domain.command(part_of=Notification)
class SendConfirmation:
    order_id: Identifier(required=True)
    recipient_id: Identifier(required=True)
    total: Float(required=True)


@domain.command_handler(part_of=Notification)
class NotificationCommandHandler:
    @handle(SendConfirmation)
    def send_confirmation(self, command: SendConfirmation):
        repo = current_domain.repository_for(Notification)
        # One confirmation per order: the order id names the notification
        notification_id = f"confirmation-{command.order_id}"
        if repo.query.filter(notification_id=notification_id).all().items:
            return
        notification = Notification(
            notification_id=notification_id,
            recipient_id=command.recipient_id,
            template="order_confirmation",
            data={"order_id": command.order_id, "total": command.total},
        )
        repo.add(notification)


# --8<-- [start:pipeline]
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        repo = current_domain.repository_for(Order)
        order = Order(
            order_id=command.order_id,
            customer_id=command.customer_id,
            items=command.items,
        )
        order.place()
        repo.add(order)
        # OrderPlaced event is raised by order.place()


# Each downstream concern handles the event independently.
# Each handler stays with Order and issues a command to its own aggregate.
@domain.event_handler(part_of=Order)
class InventoryEventHandler:
    @handle(OrderPlaced)
    def reserve_inventory(self, event: OrderPlaced):
        for item in event.items:
            current_domain.process(
                ReserveStock(
                    order_id=event.order_id,
                    product_id=item["product_id"],
                    quantity=item["quantity"],
                )
            )


@domain.event_handler(part_of=Order)
class LoyaltyEventHandler:
    @handle(OrderPlaced)
    def award_points(self, event: OrderPlaced):
        current_domain.process(
            AwardPoints(
                order_id=event.order_id,
                customer_id=event.customer_id,
                points=int(event.total),
            )
        )


@domain.event_handler(part_of=Order)
class NotificationEventHandler:
    @handle(OrderPlaced)
    def send_confirmation(self, event: OrderPlaced):
        current_domain.process(
            SendConfirmation(
                order_id=event.order_id,
                recipient_id=event.customer_id,
                total=event.total,
            )
        )


# --8<-- [end:pipeline]
