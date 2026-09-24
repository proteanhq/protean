"""
E-commerce order flow with direct cross-aggregate coupling (before events).

Anti-patterns present:
- Command handler modifies Order AND Inventory (transaction boundary violation)
- Side effects (notifications) called directly from handler
- Tight coupling between ordering and fulfillment
"""

from protean import Domain, handle
from protean.fields import Integer, String

domain = Domain()


@domain.aggregate
class Order:
    customer_id = String(required=True)
    product_id = String(required=True)
    quantity = Integer(required=True, min_value=1)
    status = String(default="DRAFT")

    def place(self) -> None:
        self.status = "PLACED"


@domain.aggregate
class Inventory:
    product_id = String(required=True, identifier=True)
    available = Integer(default=0)

    def reduce(self, quantity: int) -> None:
        if self.available < quantity:
            raise ValueError("Insufficient stock")
        self.available -= quantity


@domain.aggregate
class CustomerNotification:
    customer_id = String(required=True, identifier=True)
    last_message = String()

    def notify(self, message: str) -> None:
        self.last_message = message


@domain.command(part_of="Order")
class PlaceEcommerceOrder:
    customer_id = String(required=True)
    product_id = String(required=True)
    quantity = Integer(required=True)


@domain.command_handler(part_of=Order)
class EcommerceOrderHandler:
    @handle(PlaceEcommerceOrder)
    def place_order(self, command: PlaceEcommerceOrder) -> None:
        # Create and persist order
        order = Order(
            customer_id=command.customer_id,
            product_id=command.product_id,
            quantity=command.quantity,
        )
        order.place()
        domain.repository_for(Order).add(order)

        # VIOLATION: modifying Inventory in same handler
        inventory = domain.repository_for(Inventory).get(command.product_id)
        inventory.reduce(command.quantity)
        domain.repository_for(Inventory).add(inventory)

        # VIOLATION: modifying CustomerNotification in same handler
        notification = domain.repository_for(CustomerNotification).get(
            command.customer_id
        )
        notification.notify(
            f"Order for {command.quantity}x {command.product_id} placed!"
        )
        domain.repository_for(CustomerNotification).add(notification)


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        # Setup
        domain.repository_for(Inventory).add(
            Inventory(product_id="WIDGET-01", available=100)
        )
        domain.repository_for(CustomerNotification).add(
            CustomerNotification(customer_id="CUST-001")
        )
        # Place order
        domain.process(
            PlaceEcommerceOrder(
                customer_id="CUST-001",
                product_id="WIDGET-01",
                quantity=5,
            ),
            asynchronous=False,
        )
