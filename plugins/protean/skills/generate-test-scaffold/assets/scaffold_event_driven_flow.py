"""
Cross-aggregate event-driven testing scaffold: Order → OrderPlaced → ReserveStock → Inventory.

This example demonstrates:
- Cross-aggregate flow: an event handler in Order's cluster reacts to
  OrderPlaced and issues a ReserveStock command to Inventory
- Inventory's command handler does the write (reserving stock)
- Business rule enforcement in aggregate methods (insufficient stock)
- A redelivered event is a no-op: the command carries the order id, and
  Inventory records the order ids it has already applied
- End-to-end flow verification across aggregate boundaries
- Pytest tests for the flow, run with the fixtures in conftest.py, which set
  event and command processing to "sync" so the whole hop runs when the Order
  is persisted

Domain: When an Order is placed, an event handler on the Order aggregate
reacts to OrderPlaced and asks Inventory to reserve the requested stock. The
Inventory aggregate enforces that you cannot reserve more than available stock.
"""

from protean import Domain, current_domain, handle
from protean.fields import Identifier, Integer, List, String

domain = Domain()


# --- Commands ---


@domain.command(part_of="Inventory")
class ReserveStock:
    """Reserve stock for one placed order.

    `order_id` comes from the event, so a redelivered event reissues the same
    command and the handler can tell it has already applied it.
    """

    order_id: Identifier(required=True)
    product_id: String(required=True)
    quantity: Integer(required=True)


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

    `applied_order_ids` records which orders have already reserved stock here.
    Reserving is an update, so the stock levels alone cannot show whether a
    given order was applied; this list can.
    """

    product_id: String(required=True, max_length=50)
    available: Integer(required=True, min_value=0)
    reserved: Integer(default=0)
    applied_order_ids: List(content_type=String)

    def reserve(self, order_id, quantity):
        """Reserve stock for one order and record that the order was applied.

        Raises ValueError if insufficient stock available.
        Raises StockReserved event on success.
        """
        if quantity > self.available:
            raise ValueError(
                f"Insufficient stock: requested {quantity}, available {self.available}"
            )
        self.available -= quantity
        self.reserved += quantity
        self.applied_order_ids = [*self.applied_order_ids, order_id]
        self.raise_(
            StockReserved(
                inventory_id=self.id,
                product_id=self.product_id,
                quantity_reserved=quantity,
                remaining_available=self.available,
            )
        )


# --- Command Handler (the write path for Inventory) ---


@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    """The write path for Inventory."""

    @handle(ReserveStock)
    def reserve_stock(self, command: ReserveStock):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(product_id=command.product_id)
        if command.order_id in inventory.applied_order_ids:
            # Already applied. A redelivered OrderPlaced reissues ReserveStock,
            # and reserving again would take the stock twice.
            return
        inventory.reserve(command.order_id, command.quantity)
        repo.add(inventory)


# --- Event Handler (the cross-aggregate link, in Order's cluster) ---


@domain.event_handler(part_of=Order)
class InventoryReservationHandler:
    """React to Order's own OrderPlaced event and reserve stock.

    The handler sits in Order's cluster, because it reacts to Order's own event.
    It hands off to Inventory with a command, and Inventory's command handler
    does the write.
    """

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        """Ask Inventory to reserve stock for the placed order."""
        current_domain.process(
            ReserveStock(
                order_id=event.order_id,
                product_id=event.product_id,
                quantity=event.quantity,
            )
        )


# --- Tests ---

import pytest


class TestInventory:
    def test_reserve_moves_stock_to_reserved(self):
        inventory = Inventory(product_id="p-1", available=10)
        inventory.reserve("o-1", 4)

        assert inventory.available == 6
        assert inventory.reserved == 4
        assert inventory.applied_order_ids == ["o-1"]
        assert len(inventory._events) == 1
        assert inventory._events[0].remaining_available == 6

    def test_cannot_reserve_more_than_available(self):
        # reserve() raises ValueError and leaves the stock unchanged.
        inventory = Inventory(product_id="p-1", available=3)
        with pytest.raises(ValueError, match="Insufficient stock"):
            inventory.reserve("o-1", 5)
        assert inventory.available == 3
        assert inventory.reserved == 0
        assert inventory.applied_order_ids == []


class TestReserveStockHandler:
    def test_a_repeated_command_reserves_once(self):
        # Events are delivered at least once, so the same OrderPlaced can
        # arrive twice and issue the same ReserveStock twice. The handler is
        # called directly here, so the test does not depend on the processing
        # mode.
        inventory = Inventory(product_id="p-1", available=100)
        domain.repository_for(Inventory).add(inventory)

        command = ReserveStock(order_id="o-1", product_id="p-1", quantity=5)
        InventoryCommandHandler().reserve_stock(command)
        InventoryCommandHandler().reserve_stock(command)

        updated = domain.repository_for(Inventory).get(inventory.id)
        assert updated.available == 95
        assert updated.reserved == 5
        assert updated.applied_order_ids == ["o-1"]


class TestCrossAggregateFlow:
    def test_order_placed_reserves_inventory(self):
        # The Inventory must exist before the Order is persisted, because the
        # ReserveStock command handler loads it.
        inventory = Inventory(product_id="p-1", available=100, reserved=0)
        domain.repository_for(Inventory).add(inventory)

        order = Order.place(customer_id="c-1", product_id="p-1", quantity=5)
        domain.repository_for(Order).add(order)

        updated = domain.repository_for(Inventory).get(inventory.id)
        assert updated.available == 95
        assert updated.reserved == 5
        assert updated.applied_order_ids == [order.id]

    def test_multiple_orders_accumulate_reservations(self):
        inventory = Inventory(product_id="p-1", available=100, reserved=0)
        domain.repository_for(Inventory).add(inventory)

        for quantity in (10, 15):
            order = Order.place(customer_id="c-1", product_id="p-1", quantity=quantity)
            domain.repository_for(Order).add(order)

        updated = domain.repository_for(Inventory).get(inventory.id)
        assert updated.available == 75
        assert updated.reserved == 25
