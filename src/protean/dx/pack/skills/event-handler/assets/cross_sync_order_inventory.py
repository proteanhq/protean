"""
Cross-aggregate sync: Order → Inventory stock reduction.

This example demonstrates:
- Source aggregate (Order) raises OrderShipped event
- Event handler belongs to target aggregate (Inventory)
- Handler listens to Order's stream via stream_category
- Handler loads Inventory and reduces stock
- One aggregate per transaction pattern

Domain: When an order is shipped, inventory stock for that product
is reduced. Order and Inventory are separate aggregates with their
own consistency boundaries.
"""

from protean import Domain, handle
from protean.fields import Identifier, Integer, String

domain = Domain(__name__)
domain.config["event_processing"] = "sync"


# --- Events ---


@domain.event(part_of="Order")
class OrderShipped:
    """Raised when an order is shipped."""

    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)


# --- Source Aggregate: Order ---


@domain.aggregate
class Order:
    """Order aggregate (source of events)."""

    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    status: String(default="placed")

    def ship(self):
        """Ship the order, raising OrderShipped event."""
        self.status = "shipped"
        self.raise_(
            OrderShipped(
                order_id=self.id,
                product_id=self.product_id,
                quantity=self.quantity,
            )
        )


# --- Target Aggregate: Inventory ---


@domain.aggregate
class Inventory:
    """Inventory aggregate (target of sync)."""

    product_id: Identifier(required=True)
    stock_level: Integer(required=True)

    def reduce_stock(self, quantity):
        """Reduce stock level by the given quantity."""
        self.stock_level -= quantity


# --- Cross-Aggregate Event Handler ---


@domain.event_handler(
    part_of=Inventory,
    stream_category=Order.meta_.stream_category,
)
class InventorySyncHandler:
    """Syncs Inventory when Order events occur.

    Belongs to Inventory (part_of=Inventory) but listens to
    Order's event stream (stream_category=Order.meta_.stream_category).
    """

    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        """Reduce inventory stock when an order ships."""
        repo = domain.repository_for(Inventory)
        inventory = repo._dao.find_by(product_id=event.product_id)
        inventory.reduce_stock(event.quantity)
        repo.add(inventory)
