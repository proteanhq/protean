"""
E-commerce order flow with event-driven cross-aggregate coordination (after events).

Changes from introduce_events_ecommerce_before.py:
1. Order.place() now raises the EcommerceOrderPlaced event
2. Event handlers in Order's own cluster react to EcommerceOrderPlaced
3. They hand off with commands: ReserveStock to Inventory and NotifyCustomer
   to CustomerNotification
4. Each command handler touches only its own aggregate (proper transaction
   boundaries)
5. The order command handler only places and saves the order

Events are delivered at least once, so each receiving command handler is safe
to repeat. ReserveStock carries the order id, and Inventory records the order
ids it has already reserved stock for. NotifyCustomer carries the order id
too, and CustomerNotification records the orders it has already notified, so a
late repeat of an older order cannot overwrite a newer message.
"""

from protean import Domain, current_domain, handle
from protean.fields import Identifier, Integer, List, String

domain = Domain()

# Run the hop in-process: the event reaches its handlers when the unit of work
# that saved the order commits, and each command reaches its handler as soon as
# it is issued.
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


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
    """Stock for one product.

    `reserved_order_ids` records which orders have already reserved stock.
    Reserving is an update, so the stock level alone cannot show whether a given
    order was applied; this list can.
    """

    product_id = String(required=True, identifier=True)
    available = Integer(default=0)
    reserved_order_ids = List(content_type=String)

    def reserve(self, order_id: str, quantity: int) -> None:
        """Reserve stock for one order and record that the order was applied."""
        if self.available < quantity:
            raise ValueError("Insufficient stock")
        self.available -= quantity
        self.reserved_order_ids = [*self.reserved_order_ids, order_id]


@domain.aggregate
class CustomerNotification:
    """The latest message sent to one customer.

    `notified_order_ids` records which orders have already been notified.
    """

    customer_id = String(required=True, identifier=True)
    last_message = String()
    notified_order_ids = List(content_type=String)

    def notify(self, order_id: str, message: str) -> None:
        self.last_message = message
        self.notified_order_ids = [*self.notified_order_ids, order_id]


# --- Commands ---


@domain.command(part_of="Order")
class PlaceEcommerceOrder:
    customer_id = String(required=True)
    product_id = String(required=True)
    quantity = Integer(required=True)


@domain.command(part_of="Inventory")
class ReserveStock:
    """Reserve stock for one placed order.

    `order_id` comes from the event, so a redelivered event reissues the same
    command and the handler can tell it has already applied it.
    """

    order_id = Identifier(required=True)
    product_id = String(required=True)
    quantity = Integer(required=True)


@domain.command(part_of="CustomerNotification")
class NotifyCustomer:
    order_id = Identifier(required=True)
    customer_id = String(required=True)
    message = String(required=True)


# --- Command Handlers (single aggregate each) ---


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
        current_domain.repository_for(Order).add(order)


@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(ReserveStock)
    def reserve_stock(self, command: ReserveStock) -> None:
        repo = current_domain.repository_for(Inventory)
        inventory = repo.get(command.product_id)
        if command.order_id in inventory.reserved_order_ids:
            # Already applied. A redelivered event reissues ReserveStock, and
            # reserving again would take the stock down twice.
            return
        inventory.reserve(command.order_id, command.quantity)
        repo.add(inventory)


@domain.command_handler(part_of=CustomerNotification)
class NotificationCommandHandler:
    @handle(NotifyCustomer)
    def notify_customer(self, command: NotifyCustomer) -> None:
        repo = current_domain.repository_for(CustomerNotification)
        notification = repo.get(command.customer_id)
        if command.order_id in notification.notified_order_ids:
            # Already applied. A late repeat of an older order's event would
            # otherwise overwrite the newer message.
            return
        notification.notify(command.order_id, command.message)
        repo.add(notification)


# --- Event Handlers (in Order's cluster, hand off with commands) ---


@domain.event_handler(part_of=Order)
class InventoryOnOrderHandler:
    """React to Order's own event and ask Inventory to reserve stock.

    The handler sits in Order's cluster, because it reacts to Order's own event.
    Inventory's command handler does the write.
    """

    @handle(EcommerceOrderPlaced)
    def reserve_stock(self, event: EcommerceOrderPlaced) -> None:
        current_domain.process(
            ReserveStock(
                order_id=event.order_id,
                product_id=event.product_id,
                quantity=event.quantity,
            )
        )


@domain.event_handler(part_of=Order)
class NotificationOnOrderHandler:
    """React to Order's own event and ask CustomerNotification to notify."""

    @handle(EcommerceOrderPlaced)
    def notify_customer(self, event: EcommerceOrderPlaced) -> None:
        current_domain.process(
            NotifyCustomer(
                order_id=event.order_id,
                customer_id=event.customer_id,
                message=f"Order for {event.quantity}x {event.product_id} placed!",
            )
        )


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
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
        )
