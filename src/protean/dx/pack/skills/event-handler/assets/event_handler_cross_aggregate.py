"""
Event handler that reacts to one aggregate's event and changes another aggregate.

This example demonstrates:
- The event handler sits in Order's cluster (part_of=Order), the cluster that
  owns OrderShipped, so it needs no stream_category
- The handler hands off to Inventory by issuing a ReduceStock command
- Inventory's command handler looks the inventory up by a non-identity field
  (book_id) with find_by and reduces the stock
- Each aggregate changes only through its own command handler
- A redelivered event is a no-op: events are delivered at least once, so the
  command carries the order id and Inventory records the orders it has applied
- Synchronous event and command processing for testing

Usage:
    order = Order(book_id="BOOK-1", quantity=5, total_amount=50)
    domain.repository_for(Order).add(order)
    domain.process(ShipOrder(order_id=order.id))
    # ManageInventory reacts to OrderShipped and issues ReduceStock
"""

from protean import Domain, current_domain, handle
from protean.fields import Identifier, Integer, List, String

# Domain setup
domain = Domain()
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


@domain.command(part_of="Order")
class ShipOrder:
    """Command to ship an order."""

    order_id: Identifier(required=True)


@domain.command(part_of="Inventory")
class ReduceStock:
    """Command to reduce a book's stock for one shipped order.

    `order_id` comes from the event, so a redelivered event reissues the same
    command and the handler can tell it has already applied it.
    """

    order_id: Identifier(required=True)
    book_id: Identifier(required=True)
    quantity: Integer(required=True)


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
    """Inventory aggregate tracking stock levels.

    `applied_order_ids` records which shipped orders have already reduced this
    stock, so a repeated ReduceStock for the same order changes nothing.
    """

    book_id: Identifier(required=True)
    in_stock: Integer(required=True)
    applied_order_ids: List(content_type=String)

    def reduce_stock(self, order_id, quantity):
        """Reduce stock for one order and record that the order was applied."""
        self.in_stock -= quantity
        self.applied_order_ids = [*self.applied_order_ids, order_id]


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    """The write path for Order."""

    @handle(ShipOrder)
    def ship_order(self, command: ShipOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.ship_order()
        repo.add(order)


@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    """The write path for Inventory."""

    @handle(ReduceStock)
    def reduce_stock(self, command: ReduceStock):
        """Reduce the stock of the book in the command.

        The command carries the book id, which is not Inventory's identity, so
        the handler looks the inventory up with find_by.
        """
        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(book_id=command.book_id)
        if command.order_id in inventory.applied_order_ids:
            # Already applied. A redelivered OrderShipped reissues ReduceStock,
            # and reducing again would take the stock down twice.
            return
        inventory.reduce_stock(command.order_id, command.quantity)
        repo.add(inventory)


@domain.event_handler(part_of=Order)
class ManageInventory:
    """React to Order's own OrderShipped event and reduce stock.

    The handler sits in Order's cluster because OrderShipped belongs to Order
    (a handler that reacts to another cluster's event is what `check` reports
    as EVENT_HANDLER_FOREIGN_EVENT). It changes Inventory only through the
    ReduceStock command, so Order and Inventory never share a transaction.
    """

    @handle(OrderShipped)
    def reduce_stock_level(self, event: OrderShipped):
        """Ask Inventory to reduce stock for the shipped book."""
        current_domain.process(
            ReduceStock(
                order_id=event.order_id,
                book_id=event.book_id,
                quantity=event.quantity,
            )
        )


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Set up initial data
        order = Order(book_id="BOOK-1", quantity=10, total_amount=100)
        domain.repository_for(Order).add(order)

        inventory = Inventory(book_id="BOOK-1", in_stock=100)
        domain.repository_for(Inventory).add(inventory)

        # Ship the order: OrderShipped reaches ManageInventory, which issues
        # ReduceStock
        domain.process(ShipOrder(order_id=order.id))

        # Verify inventory was reduced
        stock = domain.repository_for(Inventory).get(inventory.id)
        print(f"Stock level: {stock.in_stock}")  # Should be 90
        assert stock.in_stock == 90
