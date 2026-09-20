"""
Cross-aggregate event-driven testing scaffold: Order → OrderPlaced → InventoryHandler → reserve.

This example demonstrates:
- Cross-aggregate event handling (Order events → Inventory handler)
- Event handler side effects (reserving stock in another aggregate)
- Business rule enforcement in aggregate methods (insufficient stock)
- End-to-end flow verification across aggregate boundaries
- Synchronous event processing for testability

Domain: When an Order is placed, an event handler on the Inventory aggregate
listens to OrderPlaced and reserves the requested stock. The Inventory aggregate
enforces that you cannot reserve more than available stock.
"""

from protean import Domain, handle
from protean.fields import Identifier, Integer, String

domain = Domain(__name__)
domain.config["event_processing"] = "sync"


# --- Events ---


@domain.event(part_of="Order")
class OrderPlaced:
    """Raised when an order is placed."""

    order_id: Identifier(required=True)
    product_id: String(required=True)
    quantity: Integer(required=True)


@domain.event(part_of="Inventory")
class StockReserved:
    """Raised when stock is successfully reserved for an order."""

    inventory_id: Identifier(required=True)
    product_id: String(required=True)
    quantity_reserved: Integer(required=True)
    remaining_available: Integer(required=True)


# --- Order Aggregate ---


@domain.aggregate
class Order:
    """Order aggregate that raises OrderPlaced on placement."""

    customer_id: String(required=True, max_length=50)
    product_id: String(required=True, max_length=50)
    quantity: Integer(required=True, min_value=1)
    status: String(default="draft")

    @classmethod
    def place(cls, customer_id, product_id, quantity):
        """Factory: create and place an order, raising OrderPlaced."""
        order = cls(
            customer_id=customer_id,
            product_id=product_id,
            quantity=quantity,
            status="placed",
        )
        order.raise_(
            OrderPlaced(
                order_id=order.id,
                product_id=order.product_id,
                quantity=order.quantity,
            )
        )
        return order


# --- Inventory Aggregate ---


@domain.aggregate
class Inventory:
    """Inventory aggregate tracking stock levels.

    Business rule: cannot reserve more than available stock.
    """

    product_id: String(required=True, max_length=50)
    available: Integer(required=True, min_value=0)
    reserved: Integer(default=0)

    def reserve(self, quantity):
        """Reserve stock for an order.

        Raises ValueError if insufficient stock available.
        Raises StockReserved event on success.
        """
        if quantity > self.available:
            raise ValueError(
                f"Insufficient stock: requested {quantity}, available {self.available}"
            )
        self.available -= quantity
        self.reserved += quantity
        self.raise_(
            StockReserved(
                inventory_id=self.id,
                product_id=self.product_id,
                quantity_reserved=quantity,
                remaining_available=self.available,
            )
        )


# --- Event Handler (cross-aggregate) ---


@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class InventoryEventHandler:
    """Handles Order events to update Inventory.

    Belongs to Inventory aggregate (part_of=Inventory) but listens
    to Order aggregate's event stream (stream_category).
    """

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        """When an order is placed, reserve stock in inventory."""
        repo = domain.repository_for(Inventory)
        inventory = repo._dao.find_by(product_id=event.product_id)
        inventory.reserve(event.quantity)
        repo.add(inventory)
