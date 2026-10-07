"""
Complete event flow where the event triggers a change in a different aggregate.

This example demonstrates the full add-event workflow for cross-aggregate coordination:
- Event raised by one aggregate (Order) triggers a change in another (Inventory)
- The event handler sits in Order's own cluster (part_of=Order), the cluster that
  owns the event
- The handler hands off to Inventory by issuing a ReduceStock command
- Inventory's command handler loads the inventory and reduces stock
- No direct coupling between Order and Inventory aggregates
- A redelivered event is a no-op: the command carries the order id, and
  Inventory records the order ids it has already applied

Scenario:
    When an order is shipped, the inventory stock level should be reduced.
    An event handler in Order's cluster reacts to OrderShipped and issues
    ReduceStock, which Inventory's command handler processes.

Workflow:
    Order.ship() → self.raise_(OrderShipped) → repository.add(order)
    → InventorySyncHandler.on_order_shipped() → domain.process(ReduceStock)
    → InventoryCommandHandler.reduce_stock() → load inventory → reduce stock → persist

Processing is synchronous, so persisting the shipped order runs the whole hop
in-process. A deployed domain leaves both asynchronous and lets the server
drive the step.

Usage:
    order = Order(order_id="ORD-001", product_id="PROD-100", quantity=5)
    order.ship()
    domain.repository_for(Order).add(order)
    # InventorySyncHandler issues ReduceStock, and Inventory's stock drops by 5
"""

from protean import Domain, current_domain, handle
from protean.fields import Identifier, Integer, List, String

# Domain setup
domain = Domain()

# Run the hop in-process: OrderShipped reaches the event handler as soon as the
# order is saved, and ReduceStock reaches its handler as soon as it is issued.
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


# --- Event (belongs to Order aggregate) ---


@domain.event(part_of="Order")
class OrderShipped:
    """Event raised when an order is shipped.

    Carries the product_id and quantity so the handler can tell
    Inventory which product to adjust and by how much.
    """

    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)


# --- Command (belongs to Inventory aggregate) ---


@domain.command(part_of="Inventory")
class ReduceStock:
    """Reduce a product's stock for one shipped order.

    `order_id` comes from the event, so a redelivered event reissues the same
    command and the handler can tell it has already applied it.
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


# --- Target Aggregate (receives the change) ---


@domain.aggregate
class Inventory:
    """Inventory aggregate tracking stock levels per product.

    `applied_order_ids` records which shipped orders have already reduced this
    stock. Reducing stock is an update, so the stock level alone cannot show
    whether a given order was applied; this list can.
    """

    product_id: Identifier(required=True)
    in_stock: Integer(required=True)
    applied_order_ids: List(content_type=String)

    def reduce_stock(self, order_id: str, quantity: int):
        """Reduce stock for one order and record that the order was applied.

        Business logic stays in the aggregate - the handler
        should NOT contain this logic directly.
        """
        if quantity > self.in_stock:
            raise ValueError(
                f"Insufficient stock: have {self.in_stock}, need {quantity}"
            )
        self.in_stock -= quantity
        self.applied_order_ids = [*self.applied_order_ids, order_id]


# --- Command Handler (the write path for Inventory) ---


@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    """The write path for Inventory."""

    @handle(ReduceStock)
    def reduce_stock(self, command: ReduceStock):
        """Load the inventory for the product, reduce its stock, and persist."""
        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(product_id=command.product_id)
        if command.order_id in inventory.applied_order_ids:
            # Already applied. Events are delivered at least once, and a
            # redelivered OrderShipped reissues ReduceStock.
            return
        inventory.reduce_stock(command.order_id, command.quantity)
        repo.add(inventory)


# --- Event Handler (in the cluster that owns the event) ---


@domain.event_handler(part_of=Order)
class InventorySyncHandler:
    """React to Order's own OrderShipped event and reduce stock.

    The handler sits in Order's cluster, because it reacts to Order's own event
    (a handler that reacts to another cluster's event is what `check` reports
    as EVENT_HANDLER_FOREIGN_EVENT). It hands off to Inventory with a command,
    and Inventory's command handler does the write.
    """

    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        """Ask Inventory to reduce stock for the shipped order."""
        current_domain.process(
            ReduceStock(
                order_id=event.order_id,
                product_id=event.product_id,
                quantity=event.quantity,
            )
        )


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
