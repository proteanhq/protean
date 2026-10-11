# --8<-- [start:full]
from protean import Domain, handle
from protean.exceptions import ValidationError
from protean.fields import (
    Dict,
    Float,
    HasMany,
    Identifier,
    Integer,
    List,
    String,
    ValueObject,
)
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
    items = HasMany("OrderItem")

    def quantities_by_title(self) -> dict[str, int]:
        """Total quantity per book, adding up lines for the same title."""
        totals: dict[str, int] = {}
        for item in self.items:
            totals[item.book_title] = totals.get(item.book_title, 0) + item.quantity
        return totals

    def confirm(self):
        self.status = "CONFIRMED"
        self.raise_(
            OrderConfirmed(
                order_id=self.id,
                customer_name=self.customer_name,
                items=[
                    {"book_title": title, "quantity": quantity}
                    for title, quantity in self.quantities_by_title().items()
                ],
            )
        )

    def complete(self):
        self.status = "COMPLETED"

    def cancel(self):
        self.status = "CANCELLED"


@domain.entity(part_of=Order)
class OrderItem:
    book_title: String(max_length=200, required=True)
    quantity: Integer(required=True)
    unit_price = ValueObject(Money)


@domain.aggregate
class Inventory:
    book_id: Identifier(required=True)
    title: String(max_length=200, required=True)
    quantity: Integer(default=0)
    reserved_order_ids = List(content_type=String)
    reserved_quantities = Dict()  # order id -> copies held for that order
    released_order_ids = List(content_type=String)

    def reserve(self, order_id: str, amount: int):
        if self.quantity < amount:
            raise ValidationError(
                {
                    "quantity": [
                        f"Insufficient stock: {self.quantity} available, {amount} requested"
                    ]
                }
            )
        self.quantity -= amount
        self.reserved_order_ids = [*self.reserved_order_ids, order_id]
        self.reserved_quantities = {**self.reserved_quantities, order_id: amount}
        self.raise_(
            InventoryReserved(order_id=order_id, book_title=self.title, quantity=amount)
        )

    def release(self, order_id: str):
        if order_id in self.released_order_ids:
            return  # already released
        # Return what this order holds, whatever a command says. An order
        # released before its reservation arrives holds nothing, and the
        # release still counts, so that late reservation is skipped.
        self.quantity += self.reserved_quantities.get(order_id, 0)
        self.reserved_quantities = {
            held_for: amount
            for held_for, amount in self.reserved_quantities.items()
            if held_for != order_id
        }
        self.released_order_ids = [*self.released_order_ids, order_id]


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
    items = List(content_type=Dict)


@domain.event(part_of=Inventory)
class InventoryReserved:
    order_id: Identifier(required=True)
    book_title: String(max_length=200, required=True)
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
    book_title: String(max_length=200, required=True)
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
    order_id: Identifier(required=True)
    book_title: String(max_length=200, required=True)


# --8<-- [start:process_manager]
@domain.process_manager(stream_categories=["order", "inventory", "shipment"])
class OrderFulfillmentPM:
    """Coordinates the order fulfillment workflow across aggregates."""

    order_id: Identifier(required=True)
    items = List(content_type=Dict)
    awaiting_titles = List(content_type=String)

    @handle(OrderConfirmed, start=True, correlate="order_id")
    def on_order_confirmed(self, event: OrderConfirmed):
        """Step 1: Order confirmed. Reserve each title."""
        self.order_id = event.order_id
        self.items = event.items
        self.awaiting_titles = [item["book_title"] for item in event.items]
        for item in event.items:
            current_domain.process(
                ReserveInventory(
                    order_id=event.order_id,
                    book_title=item["book_title"],
                    quantity=item["quantity"],
                )
            )

    @handle(InventoryReserved, correlate="order_id")
    def on_inventory_reserved(self, event: InventoryReserved):
        """Step 2: Once every title is reserved, create the shipment."""
        if event.book_title not in self.awaiting_titles:
            return  # a repeated event for a title already counted
        self.awaiting_titles = [
            title for title in self.awaiting_titles if title != event.book_title
        ]
        if self.awaiting_titles:
            return
        order = current_domain.repository_for(Order).get(self.order_id)
        current_domain.process(
            CreateShipment(
                order_id=self.order_id,
                address=order.shipping_address or "",
            )
        )

    @handle(ShipmentCreated, correlate="order_id", end=True)
    def on_shipment_created(self, event: ShipmentCreated):
        """Step 3: Shipment created — complete the order."""
        current_domain.process(CompleteOrder(order_id=event.order_id))

    @handle(ShipmentFailed, correlate="order_id", end=True)
    def on_shipment_failed(self, event: ShipmentFailed):
        """Compensation: Shipment failed. Release the stock and cancel the order."""
        for item in self.items:
            current_domain.process(
                ReleaseInventory(order_id=event.order_id, book_title=item["book_title"])
            )
        current_domain.process(CancelOrder(order_id=event.order_id))


# --8<-- [end:process_manager]


# --8<-- [start:handlers]
@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(ReserveInventory)
    def reserve(self, command: ReserveInventory) -> None:
        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(title=command.book_title)
        if (
            command.order_id in inventory.reserved_order_ids
            or command.order_id in inventory.released_order_ids
        ):
            return  # reserved before, or already released by compensation
        inventory.reserve(command.order_id, command.quantity)
        repo.add(inventory)

    @handle(ReleaseInventory)
    def release(self, command: ReleaseInventory) -> None:
        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(title=command.book_title)
        inventory.release(command.order_id)
        repo.add(inventory)


@domain.command_handler(part_of=Shipment)
class ShipmentCommandHandler:
    @handle(CreateShipment)
    def create(self, command: CreateShipment) -> None:
        repo = current_domain.repository_for(Shipment)
        if repo.query.filter(order_id=command.order_id).all().items:
            return  # this order already has a shipment
        shipment = Shipment(order_id=command.order_id)
        shipment.create_shipment(command.address)
        repo.add(shipment)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(CompleteOrder)
    def complete(self, command: CompleteOrder) -> None:
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.complete()
        repo.add(order)

    @handle(CancelOrder)
    def cancel(self, command: CancelOrder) -> None:
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.cancel()
        repo.add(order)


# --8<-- [end:handlers]


domain.init(traverse=False)


# --8<-- [start:tests]
# tests/test_process_managers.py (example)


def place_confirmed_order(address: str) -> Order:
    order = Order(
        customer_name="Alice",
        shipping_address=address,
        items=[
            OrderItem(book_title="Dune", quantity=2, unit_price=Money(amount=15.99))
        ],
    )
    repo = domain.repository_for(Order)
    repo.add(order)
    order.confirm()
    repo.add(order)  # with sync processing, the whole chain runs here
    return repo.get(order.id)


def test_fulfillment_happy_path():
    """Order confirmed → inventory reserved → shipment created → order completed."""
    with domain.domain_context():
        inventory = Inventory(book_id="book-1", title="Dune", quantity=10)
        domain.repository_for(Inventory).add(inventory)

        order = place_confirmed_order("123 Main St")

        assert order.status == "COMPLETED"
        assert domain.repository_for(Inventory).get(inventory.id).quantity == 8


def test_fulfillment_compensation():
    """Shipment failed → inventory released → order cancelled."""
    with domain.domain_context():
        inventory = Inventory(book_id="book-1", title="Dune", quantity=10)
        domain.repository_for(Inventory).add(inventory)

        order = place_confirmed_order("")  # an empty address fails the shipment

        assert order.status == "CANCELLED"
        assert domain.repository_for(Inventory).get(inventory.id).quantity == 10


# --8<-- [end:tests]
# --8<-- [end:full]
