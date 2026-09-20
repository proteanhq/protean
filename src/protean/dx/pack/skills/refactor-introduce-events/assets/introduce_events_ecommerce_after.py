"""
E-commerce order flow with event-driven cross-aggregate coordination (after events).

Changes from introduce_events_ecommerce_before.py:
1. Order.place() now raises OrderPlaced event
2. InventoryHandler reacts to OrderPlaced to reserve stock
3. NotificationHandler reacts to OrderPlaced to notify customer
4. Each handler touches only its own aggregate (proper transaction boundaries)
5. Command handler is now 3 lines
"""

from protean import Domain, handle
from protean.fields import Identifier, Integer, String

domain = Domain()


# --- Events ---


@domain.event(part_of="Order")
class EcommerceOrderPlaced:
    order_id = Identifier(required=True)
    customer_id = String(required=True)
    product_id = String(required=True)
    quantity = Integer(required=True)


# --- Source Aggregate ---


@domain.aggregate
class Order:
    customer_id = String(required=True)
    product_id = String(required=True)
    quantity = Integer(required=True, min_value=1)
    status = String(default="DRAFT")

    def place(self) -> None:
        """Place the order and announce it via event."""
        self.status = "PLACED"
        self.raise_(
            EcommerceOrderPlaced(
                order_id=self.id,
                customer_id=self.customer_id,
                product_id=self.product_id,
                quantity=self.quantity,
            )
        )


# --- Target Aggregates ---


@domain.aggregate
class Inventory:
    product_id = String(required=True, identifier=True)
    available = Integer(default=0)

    def reserve(self, quantity: int) -> None:
        """Reserve stock for an order."""
        if self.available < quantity:
            raise ValueError("Insufficient stock")
        self.available -= quantity


@domain.aggregate
class CustomerNotification:
    customer_id = String(required=True, identifier=True)
    last_message = String()

    def notify(self, message: str) -> None:
        self.last_message = message


# --- Command ---


@domain.command(part_of="Order")
class PlaceEcommerceOrder:
    customer_id = String(required=True)
    product_id = String(required=True)
    quantity = Integer(required=True)


# --- Thin Command Handler (single aggregate only) ---


@domain.command_handler(part_of=Order)
class EcommerceOrderHandler:
    @handle(PlaceEcommerceOrder)
    def place_order(self, command: PlaceEcommerceOrder) -> None:
        order = Order(
            customer_id=command.customer_id,
            product_id=command.product_id,
            quantity=command.quantity,
        )
        order.place()
        domain.repository_for(Order).add(order)


# --- Event Handlers (each touches only its own aggregate) ---


@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class InventoryOnOrderHandler:
    @handle(EcommerceOrderPlaced)
    def reserve_stock(self, event: EcommerceOrderPlaced) -> None:
        inventory = domain.repository_for(Inventory).get(event.product_id)
        inventory.reserve(event.quantity)
        domain.repository_for(Inventory).add(inventory)


@domain.event_handler(
    part_of=CustomerNotification, stream_category=Order.meta_.stream_category
)
class NotificationOnOrderHandler:
    @handle(EcommerceOrderPlaced)
    def notify_customer(self, event: EcommerceOrderPlaced) -> None:
        notification = domain.repository_for(CustomerNotification).get(
            event.customer_id
        )
        notification.notify(f"Order for {event.quantity}x {event.product_id} placed!")
        domain.repository_for(CustomerNotification).add(notification)


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        domain.config["event_processing"] = "sync"
        domain.repository_for(Inventory).add(
            Inventory(product_id="WIDGET-01", available=100)
        )
        domain.repository_for(CustomerNotification).add(
            CustomerNotification(customer_id="CUST-001")
        )
        domain.process(
            PlaceEcommerceOrder(
                customer_id="CUST-001",
                product_id="WIDGET-01",
                quantity=5,
            ),
            asynchronous=False,
        )
