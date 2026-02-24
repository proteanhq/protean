# --8<-- [start:full]
from protean import Domain, handle
from protean.fields import Float, Identifier, Integer, String
from protean.utils.globals import current_domain

domain = Domain()
domain.config["command_processing"] = "sync"
domain.config["event_processing"] = "sync"


@domain.value_object
class Money:
    currency: String(max_length=3, default="USD")
    amount: Float(required=True)


@domain.aggregate
class Order:
    customer_name: String(max_length=150, required=True)
    status: String(max_length=20, default="PENDING")
    shipping_address: String(max_length=500)

    def confirm(self):
        self.status = "CONFIRMED"
        self.raise_(OrderConfirmed(order_id=self.id, customer_name=self.customer_name))

    def complete(self):
        self.status = "COMPLETED"

    def cancel(self):
        self.status = "CANCELLED"


@domain.aggregate
class Inventory:
    book_id: Identifier(required=True)
    title: String(max_length=200, required=True)
    quantity: Integer(default=0)

    def reserve(self, amount: int):
        self.quantity -= amount
        self.raise_(InventoryReserved(book_id=self.book_id, quantity=amount))

    def release(self, amount: int):
        self.quantity += amount


# --8<-- [start:shipping]
@domain.aggregate
class Shipment:
    order_id: Identifier(required=True)
    status: String(max_length=20, default="PENDING")
    tracking_number: String(max_length=50)

    def create_shipment(self, address: str):
        """Attempt to create a shipment. May fail if address is invalid."""
        if not address or address.strip() == "":
            self.status = "FAILED"
            self.raise_(
                ShipmentFailed(order_id=self.order_id, reason="Invalid address")
            )
        else:
            self.status = "CREATED"
            self.tracking_number = f"TRK-{self.order_id[:8]}"
            self.raise_(
                ShipmentCreated(
                    order_id=self.order_id, tracking_number=self.tracking_number
                )
            )


# --8<-- [end:shipping]


# Events
@domain.event(part_of=Order)
class OrderConfirmed:
    order_id: Identifier(required=True)
    customer_name: String(max_length=150, required=True)


@domain.event(part_of=Inventory)
class InventoryReserved:
    book_id: Identifier(required=True)
    quantity: Integer(required=True)


@domain.event(part_of=Shipment)
class ShipmentCreated:
    order_id: Identifier(required=True)
    tracking_number: String(max_length=50)


@domain.event(part_of=Shipment)
class ShipmentFailed:
    order_id: Identifier(required=True)
    reason: String(max_length=500)


# Commands
@domain.command(part_of=Inventory)
class ReserveInventory:
    order_id: Identifier(required=True)
    book_id: Identifier(required=True)
    quantity: Integer(required=True)


@domain.command(part_of=Shipment)
class CreateShipment:
    order_id: Identifier(required=True)
    address: String(max_length=500)


@domain.command(part_of=Order)
class CompleteOrder:
    order_id: Identifier(required=True)


@domain.command(part_of=Order)
class CancelOrder:
    order_id: Identifier(required=True)


@domain.command(part_of=Inventory)
class ReleaseInventory:
    book_id: Identifier(required=True)
    quantity: Integer(required=True)


# --8<-- [start:process_manager]
@domain.process_manager(stream_categories=["order", "inventory", "shipment"])
class OrderFulfillmentPM:
    """Coordinates the order fulfillment workflow across aggregates."""

    order_id: Identifier(required=True)

    @handle(OrderConfirmed, start=True, correlate="order_id")
    def on_order_confirmed(self, event: OrderConfirmed):
        """Step 1: Order confirmed — reserve inventory."""
        current_domain.process(
            ReserveInventory(
                order_id=event.order_id,
                book_id="placeholder",  # In a real system, load order items
                quantity=1,
            )
        )

    @handle(InventoryReserved, correlate={"order_id": "book_id"})
    def on_inventory_reserved(self, event: InventoryReserved):
        """Step 2: Inventory reserved — create shipment."""
        order = current_domain.repository_for(Order).get(self.order_id)
        current_domain.process(
            CreateShipment(
                order_id=self.order_id,
                address=order.shipping_address or "",
            )
        )

    @handle(ShipmentCreated, correlate="order_id")
    def on_shipment_created(self, event: ShipmentCreated):
        """Step 3: Shipment created — complete the order."""
        current_domain.process(CompleteOrder(order_id=event.order_id))
        self.mark_as_complete()

    @handle(ShipmentFailed, correlate="order_id")
    def on_shipment_failed(self, event: ShipmentFailed):
        """Compensation: Shipment failed — release inventory and cancel order."""
        current_domain.process(ReleaseInventory(book_id="placeholder", quantity=1))
        current_domain.process(CancelOrder(order_id=event.order_id))
        self.mark_as_complete()


# --8<-- [end:process_manager]


domain.init(traverse=False)


# --8<-- [start:tests]
# tests/test_process_managers.py (example)


def test_fulfillment_happy_path():
    """Order confirmed → inventory reserved → shipment created → order completed."""
    # This test would use sync processing to verify the full chain
    pass


def test_fulfillment_compensation():
    """Shipment failed → inventory released → order cancelled."""
    # This test would verify compensation logic
    pass


# --8<-- [end:tests]
# --8<-- [end:full]
