# --8<-- [start:full]
from protean import Domain, handle, invariant
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

domain = Domain("bookshelf")
domain.config["command_processing"] = "sync"
domain.config["event_processing"] = "sync"


@domain.value_object
class Money:
    currency: String(max_length=3, default="USD")
    amount: Float(required=True)


@domain.aggregate
class Inventory:
    book_id: Identifier(required=True)
    title: String(max_length=200, required=True)
    quantity: Integer(default=0)
    reserved_order_ids = List(content_type=String)

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


@domain.aggregate
class Order:
    customer_name: String(max_length=150, required=True)
    status: String(max_length=20, default="PENDING")
    items = HasMany("OrderItem")

    def confirm(self):
        self.status = "CONFIRMED"
        self.raise_(
            OrderConfirmed(
                order_id=self.id,
                items=[
                    {"book_title": item.book_title, "quantity": item.quantity}
                    for item in self.items
                ],
            )
        )


@domain.entity(part_of=Order)
class OrderItem:
    book_title: String(max_length=200, required=True)
    quantity: Integer(required=True)
    unit_price = ValueObject(Money)


@domain.event(part_of=Order)
class OrderConfirmed:
    order_id: Identifier(required=True)
    items = List(content_type=Dict)


# --8<-- [start:service]
@domain.domain_service(part_of=[Order, Inventory])
class OrderFulfillmentService:
    """Validates inventory availability before confirming an order."""

    def __init__(self, order, inventories):
        super().__init__(order, *inventories)
        self.order = order
        self.inventories = inventories

    @invariant.pre
    def all_items_in_stock(self):
        """Check that every order item has sufficient inventory."""
        inventory_by_title = {inv.title: inv for inv in self.inventories}

        for item in self.order.items:
            inv = inventory_by_title.get(item.book_title)
            if inv is None:
                raise ValidationError(
                    {"_entity": [f"No inventory record for '{item.book_title}'"]}
                )
            if inv.quantity < item.quantity:
                raise ValidationError(
                    {
                        "_entity": [
                            (
                                f"Insufficient stock for '{item.book_title}': "
                                f"{inv.quantity} available, {item.quantity} requested"
                            )
                        ]
                    }
                )

    def confirm_order(self):
        """Confirm the order. The pre-invariant has already checked stock."""
        self.order.confirm()
        return self.order


# --8<-- [end:service]


@domain.command(part_of=Order)
class ConfirmOrder:
    order_id: Identifier(required=True)


@domain.command(part_of=Inventory)
class ReserveInventory:
    order_id: Identifier(required=True)
    book_title: String(max_length=200, required=True)
    quantity: Integer(required=True)


# --8<-- [start:handler]
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(ConfirmOrder)
    def confirm_order(self, command: ConfirmOrder) -> None:
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)

        # Load inventory records for all items in the order
        inv_repo = current_domain.repository_for(Inventory)
        inventories = []
        for item in order.items:
            inv_results = inv_repo.query.filter(title=item.book_title).all()
            if inv_results.items:
                inventories.append(inv_results.items[0])

        # Delegate to the domain service
        service = OrderFulfillmentService(order, inventories)
        service.confirm_order()

        # Persist only the order. Inventory reserves through OrderConfirmed.
        repo.add(order)


# --8<-- [end:handler]


# --8<-- [start:reservation]
@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderConfirmed)
    def reserve_inventory(self, event: OrderConfirmed) -> None:
        for item in event.items:
            current_domain.process(
                ReserveInventory(
                    order_id=event.order_id,
                    book_title=item["book_title"],
                    quantity=item["quantity"],
                )
            )


@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(ReserveInventory)
    def reserve(self, command: ReserveInventory) -> None:
        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(title=command.book_title)
        if command.order_id in inventory.reserved_order_ids:
            return  # already reserved; a redelivered event must not reserve twice
        inventory.reserve(command.order_id, command.quantity)
        repo.add(inventory)


# --8<-- [end:reservation]


domain.init(traverse=False)


# --8<-- [start:tests]
# tests/test_domain_services.py (example tests)


def test_confirm_order_with_stock():
    """Order is confirmed when inventory is sufficient."""
    with domain.domain_context():
        inv = Inventory(book_id="book-1", title="Dune", quantity=10)
        order = Order(
            customer_name="Alice",
            items=[
                OrderItem(book_title="Dune", quantity=2, unit_price=Money(amount=15.99))
            ],
        )

        service = OrderFulfillmentService(order, [inv])
        service.confirm_order()

        assert order.status == "CONFIRMED"
        assert inv.quantity == 10  # the service checks stock; reserving comes later


def test_confirm_order_out_of_stock():
    """Order fails when inventory is insufficient."""
    with domain.domain_context():
        inv = Inventory(book_id="book-1", title="Dune", quantity=1)
        order = Order(
            customer_name="Alice",
            items=[
                OrderItem(book_title="Dune", quantity=5, unit_price=Money(amount=15.99))
            ],
        )

        try:
            service = OrderFulfillmentService(order, [inv])
            service.confirm_order()
            raise AssertionError("Should have raised ValidationError")
        except ValidationError as e:
            assert "Insufficient stock" in str(e.messages)


# --8<-- [end:tests]
# --8<-- [end:full]
