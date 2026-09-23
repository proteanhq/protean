"""
Complete event flow where the event handler belongs to a different aggregate.

This example demonstrates the full add-event workflow for cross-aggregate coordination:
- Event raised by one aggregate (Order) triggers a reaction in another (Inventory)
- Event handler uses stream_category to listen to a foreign aggregate's stream
- The core DDD pattern for eventual consistency between aggregates
- No direct coupling between Order and Inventory aggregates

Scenario:
    When an order is shipped, the inventory stock level should be reduced.
    The Inventory aggregate's event handler listens to the Order aggregate's
    event stream and reacts to OrderShipped events.

Workflow:
    Order.ship() → self.raise_(OrderShipped) → repository.add(order)
    → ManageInventory.on_order_shipped() → load inventory → reduce stock → persist

Usage:
    order = Order(order_id="ORD-001", product_id="PROD-100", quantity=5)
    order.ship()
    domain.repository_for(Order).add(order)
    # ManageInventory handler automatically processes OrderShipped event
"""

from protean import Domain, handle
from protean.fields import Identifier, Integer, String

# Domain setup
domain = Domain()
domain.config["event_processing"] = "sync"


# --- Event (belongs to Order aggregate) ---


@domain.event(part_of="Order")
class OrderShipped:
    """Event raised when an order is shipped.

    Carries the product_id and quantity so the Inventory handler
    knows which product to adjust and by how much.
    """

    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)


# --- Source Aggregate (raises the event) ---


@domain.aggregate
class Order:
    """Order aggregate that raises events when state changes."""

    order_id: Identifier(identifier=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    status: String(default="pending")

    def ship(self):
        """Ship the order, raising OrderShipped event.

        Guards ensure only pending orders can be shipped.
        """
        if self.status != "pending":
            raise ValueError(f"Cannot ship order in '{self.status}' status")
        self.status = "shipped"

        self.raise_(
            OrderShipped(
                order_id=self.order_id,
                product_id=self.product_id,
                quantity=self.quantity,
            )
        )


# --- Target Aggregate (receives the side effect) ---


@domain.aggregate
class Inventory:
    """Inventory aggregate tracking stock levels per product."""

    product_id: Identifier(required=True)
    in_stock: Integer(required=True)

    def reduce_stock(self, quantity: int):
        """Reduce stock level by the given quantity.

        Business logic stays in the aggregate - the handler
        should NOT contain this logic directly.
        """
        if quantity > self.in_stock:
            raise ValueError(
                f"Insufficient stock: have {self.in_stock}, need {quantity}"
            )
        self.in_stock -= quantity


# --- Event Handler (cross-aggregate) ---


@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class ManageInventory:
    """Event handler that syncs Inventory state based on Order events.

    Key pattern:
    - part_of=Inventory: this handler belongs to the Inventory aggregate
    - stream_category=Order.meta_.stream_category: listens to Order's event stream

    This is the core cross-aggregate coordination pattern in DDD.
    No direct coupling between Order and Inventory - only events connect them.
    """

    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        """React to OrderShipped by reducing inventory stock.

        Loads the inventory record for the shipped product,
        reduces stock by the ordered quantity, and persists.
        """
        repo = domain.repository_for(Inventory)
        inventory = repo._dao.find_by(product_id=event.product_id)
        inventory.reduce_stock(event.quantity)
        repo.add(inventory)


# Example usage
if __name__ == "__main__":  # pragma: no cover
    domain.init(traverse=False)

    with domain.domain_context():
        # Set up initial inventory
        inventory = Inventory(product_id="PROD-100", in_stock=50)
        domain.repository_for(Inventory).add(inventory)

        # Create and ship an order
        order = Order(order_id="ORD-001", product_id="PROD-100", quantity=5)
        order.ship()
        domain.repository_for(Order).add(order)

        # Verify inventory was reduced
        stock = domain.repository_for(Inventory).get(inventory.id)
        print(f"Stock level: {stock.in_stock}")  # Should be 45
