"""
Event handler that belongs to one aggregate but listens to another aggregate's events.

This example demonstrates:
- Cross-aggregate event handling using stream_category parameter
- Event handler with part_of pointing to one aggregate (Inventory)
  but stream_category pointing to the Order aggregate's stream
- The core DDD pattern: reacting to state changes in one aggregate
  to update another aggregate
- Synchronous event processing for testing

Usage:
    order = Order(book_id="BOOK-1", quantity=5, total_amount=50)
    order.ship_order()
    domain.repository_for(Order).add(order)
    # ManageInventory handler automatically processes OrderShipped event
"""

from protean import Domain, handle
from protean.fields import Identifier, Integer, String

# Domain setup
domain = Domain()
domain.config["event_processing"] = "sync"


@domain.event(part_of="Order")
class OrderShipped:
    """Event raised when an order is shipped."""

    order_id: Identifier(required=True)
    book_id: Identifier(required=True)
    quantity: Integer(required=True)
    total_amount: Integer(required=True)


@domain.aggregate
class Order:
    """Order aggregate that raises events when shipped."""

    book_id: Identifier(required=True)
    quantity: Integer(required=True)
    total_amount: Integer(required=True)
    status: String(choices=["PENDING", "SHIPPED", "DELIVERED"], default="PENDING")

    def ship_order(self):
        """Ship the order, raising OrderShipped event."""
        self.status = "SHIPPED"
        self.raise_(
            OrderShipped(
                order_id=self.id,
                book_id=self.book_id,
                quantity=self.quantity,
                total_amount=self.total_amount,
            )
        )


@domain.aggregate
class Inventory:
    """Inventory aggregate tracking stock levels."""

    book_id: Identifier(required=True)
    in_stock: Integer(required=True)


@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class ManageInventory:
    """Event handler that syncs Inventory state with Order events.

    This handler belongs to the Inventory aggregate (part_of=Inventory)
    but listens to events from the Order aggregate's stream
    (stream_category=Order.meta_.stream_category).

    This is the core cross-aggregate coordination pattern in DDD:
    - Order aggregate raises OrderShipped event
    - ManageInventory handler picks up the event
    - Handler updates Inventory aggregate's stock levels
    - No direct coupling between Order and Inventory aggregates
    """

    @handle(OrderShipped)
    def reduce_stock_level(self, event: OrderShipped):
        """Handle OrderShipped by reducing inventory stock level.

        Loads the inventory record matching the shipped book,
        decreases stock by the ordered quantity, and persists.
        """
        repo = domain.repository_for(Inventory)
        inventory = repo._dao.find_by(book_id=event.book_id)
        inventory.in_stock -= event.quantity
        repo.add(inventory)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Set up initial data
        order = Order(book_id="BOOK-1", quantity=10, total_amount=100)
        domain.repository_for(Order).add(order)

        inventory = Inventory(book_id="BOOK-1", in_stock=100)
        domain.repository_for(Inventory).add(inventory)

        # Ship the order - triggers event handler
        order.ship_order()
        domain.repository_for(Order).add(order)

        # Verify inventory was reduced
        stock = domain.repository_for(Inventory).get(inventory.id)
        print(f"Stock level: {stock.in_stock}")  # Should be 90
        assert stock.in_stock == 90
