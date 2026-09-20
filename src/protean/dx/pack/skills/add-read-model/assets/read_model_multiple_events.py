"""
Read model with multiple events: Inventory tracking with stock adjustments.

This example demonstrates:
- A projection tracking warehouse inventory through multiple event types
- Projector handling create, restock, reserve, and release events
- Computed fields in the projection (available = stock - reserved)
- Multiple aggregate methods each raising different events
- Progressive state changes reflected in the read model

Domain: A warehouse inventory tracker where the InventoryStatus projection
provides real-time stock levels including reservations.
"""

from protean import Domain
from protean.core.projector import on
from protean.fields import Float, Identifier, Integer, String

domain = Domain(__name__)
domain.config["event_processing"] = "sync"


# --- Events ---


@domain.event(part_of="Warehouse")
class ItemStocked:
    """Raised when a new item is added to the warehouse."""

    warehouse_id: Identifier(required=True)
    sku: String(required=True)
    item_name: String(required=True)
    quantity: Integer(required=True)
    unit_cost: Float(required=True)


@domain.event(part_of="Warehouse")
class ItemRestocked:
    """Raised when additional stock is added for an existing item."""

    warehouse_id: Identifier(required=True)
    sku: String(required=True)
    added_quantity: Integer(required=True)


@domain.event(part_of="Warehouse")
class StockReserved:
    """Raised when stock is reserved for an order."""

    warehouse_id: Identifier(required=True)
    sku: String(required=True)
    reserved_quantity: Integer(required=True)


@domain.event(part_of="Warehouse")
class ReservationReleased:
    """Raised when a reservation is released back to available stock."""

    warehouse_id: Identifier(required=True)
    sku: String(required=True)
    released_quantity: Integer(required=True)


# --- Aggregate (write model) ---


@domain.aggregate
class Warehouse:
    """Warehouse aggregate tracking stock for a single SKU."""

    sku: String(required=True, max_length=50)
    item_name: String(required=True, max_length=200)
    total_stock: Integer(default=0)
    reserved: Integer(default=0)
    unit_cost: Float(default=0.0)

    @classmethod
    def stock_item(cls, sku, item_name, quantity, unit_cost):
        """Add a new item to the warehouse."""
        warehouse = cls(
            sku=sku,
            item_name=item_name,
            total_stock=quantity,
            unit_cost=unit_cost,
        )
        warehouse.raise_(
            ItemStocked(
                warehouse_id=warehouse.id,
                sku=sku,
                item_name=item_name,
                quantity=quantity,
                unit_cost=unit_cost,
            )
        )
        return warehouse

    def restock(self, quantity):
        """Add more stock for this item."""
        self.total_stock += quantity
        self.raise_(
            ItemRestocked(
                warehouse_id=self.id,
                sku=self.sku,
                added_quantity=quantity,
            )
        )

    def reserve(self, quantity):
        """Reserve stock for an order."""
        self.reserved += quantity
        self.raise_(
            StockReserved(
                warehouse_id=self.id,
                sku=self.sku,
                reserved_quantity=quantity,
            )
        )

    def release_reservation(self, quantity):
        """Release reserved stock back to available."""
        self.reserved -= quantity
        self.raise_(
            ReservationReleased(
                warehouse_id=self.id,
                sku=self.sku,
                released_quantity=quantity,
            )
        )


# --- Projection (read model) ---


@domain.projection
class InventoryStatus:
    """Real-time inventory status for warehouse items.

    Tracks total stock, reserved stock, available stock, and value.
    Populated by the InventoryStatusProjector from warehouse events.
    """

    warehouse_id: Identifier(identifier=True, required=True)
    sku: String(max_length=50, required=True)
    item_name: String(max_length=200, required=True)
    total_stock: Integer(default=0)
    reserved: Integer(default=0)
    available: Integer(default=0)
    unit_cost: Float(default=0.0)


# --- Projector ---


@domain.projector(projector_for=InventoryStatus, aggregates=[Warehouse])
class InventoryStatusProjector:
    """Maintains the InventoryStatus projection from Warehouse events.

    Handles all stock lifecycle events: initial stocking, restocking,
    reservations, and reservation releases.
    """

    @on(ItemStocked)
    def on_item_stocked(self, event: ItemStocked):
        """Create an inventory status record for a newly stocked item."""
        repo = domain.repository_for(InventoryStatus)
        status = InventoryStatus(
            warehouse_id=event.warehouse_id,
            sku=event.sku,
            item_name=event.item_name,
            total_stock=event.quantity,
            reserved=0,
            available=event.quantity,
            unit_cost=event.unit_cost,
        )
        repo.add(status)

    @on(ItemRestocked)
    def on_item_restocked(self, event: ItemRestocked):
        """Update stock levels when additional stock arrives."""
        repo = domain.repository_for(InventoryStatus)
        status = repo.get(event.warehouse_id)
        status.total_stock += event.added_quantity
        status.available += event.added_quantity
        repo.add(status)

    @on(StockReserved)
    def on_stock_reserved(self, event: StockReserved):
        """Update reserved and available when stock is reserved."""
        repo = domain.repository_for(InventoryStatus)
        status = repo.get(event.warehouse_id)
        status.reserved += event.reserved_quantity
        status.available -= event.reserved_quantity
        repo.add(status)

    @on(ReservationReleased)
    def on_reservation_released(self, event: ReservationReleased):
        """Update reserved and available when reservation is released."""
        repo = domain.repository_for(InventoryStatus)
        status = repo.get(event.warehouse_id)
        status.reserved -= event.released_quantity
        status.available += event.released_quantity
        repo.add(status)
