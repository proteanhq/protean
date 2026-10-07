"""
Cross-aggregate sync: Order → Inventory stock reduction.

This example demonstrates:
- Source aggregate (Order) raises OrderShipped event
- Event handler sits in Order's own cluster (part_of=Order), the cluster that
  owns the event
- The handler hands off to Inventory by issuing a ReduceStock command
- Inventory's command handler loads the inventory and reduces stock
- One aggregate per transaction pattern
- A redelivered event is a no-op: the command carries the order id, and
  Inventory records the order ids it has already applied

Domain: When an order is shipped, inventory stock for that product
is reduced. Order and Inventory are separate aggregates with their
own consistency boundaries.

Processing is synchronous, so shipping an order runs the whole hop in-process,
with no broker and no server. A deployed domain leaves both asynchronous and
lets the server drive the step.

Usage:
    from cross_sync_order_inventory import Inventory, Order, ShipOrder, domain

    domain.init(traverse=False)
    with domain.domain_context():
        domain.repository_for(Inventory).add(
            Inventory(product_id="SKU-1", stock_level=10)
        )
        order = Order(product_id="SKU-1", quantity=3)
        domain.repository_for(Order).add(order)

        # Ships the order, which reduces the stock to 7.
        domain.process(ShipOrder(order_id=order.id))
"""

from protean import Domain, current_domain, handle
from protean.fields import Identifier, Integer, List, String

domain = Domain(__name__)

# Run the hop in-process: OrderShipped reaches the event handler as soon as the
# order is saved, and ReduceStock reaches its handler as soon as it is issued.
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


# --- Commands ---


@domain.command(part_of="Order")
class ShipOrder:
    """Ship an order."""

    order_id: Identifier(required=True)


@domain.command(part_of="Inventory")
class ReduceStock:
    """Reduce a product's stock for one shipped order.

    `order_id` comes from the event, so a redelivered event reissues the same
    command and the handler can tell it has already applied it.
    """

    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)


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
    """Inventory aggregate (target of sync).

    `applied_order_ids` records which shipped orders have already reduced this
    stock. Reducing stock is an update, so the current stock level alone cannot
    show whether a given order was applied; this list can.
    """

    product_id: Identifier(required=True)
    stock_level: Integer(required=True)
    applied_order_ids: List(content_type=String)

    def reduce_stock(self, order_id, quantity):
        """Reduce stock for one order and record that the order was applied."""
        self.stock_level -= quantity
        self.applied_order_ids = [*self.applied_order_ids, order_id]


# --- Command handlers (the write path for each aggregate) ---


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    """The write path for Order."""

    @handle(ShipOrder)
    def ship_order(self, command: ShipOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.ship()
        repo.add(order)


@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    """The write path for Inventory."""

    @handle(ReduceStock)
    def reduce_stock(self, command: ReduceStock):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(product_id=command.product_id)
        if command.order_id in inventory.applied_order_ids:
            # Already applied. A redelivered OrderShipped reissues ReduceStock,
            # and reducing again would take the stock down twice.
            return
        inventory.reduce_stock(command.order_id, command.quantity)
        repo.add(inventory)


# --- The cross-aggregate link: an event handler in Order's cluster ---


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
