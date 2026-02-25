# --8<-- [start:full]
from protean import Domain, handle, invariant
from protean.fields import Float, HasMany, Identifier, Integer, String, ValueObject
from protean.utils.globals import current_domain
from protean.exceptions import ValidationError

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

    def reserve(self, amount: int):
        if self.quantity < amount:
            raise ValidationError(
                {
                    "quantity": [
                        f"Insufficient stock: {self.quantity} available, {amount} requested"
                    ]
                }
            )
        self.quantity -= amount


@domain.aggregate
class Order:
    customer_name: String(max_length=150, required=True)
    status: String(max_length=20, default="PENDING")
    items = HasMany("OrderItem")

    def confirm(self):
        self.status = "CONFIRMED"


@domain.entity(part_of=Order)
class OrderItem:
    book_title: String(max_length=200, required=True)
    quantity: Integer(required=True)
    unit_price = ValueObject(Money)


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
                            f"Insufficient stock for '{item.book_title}': "
                            f"{inv.quantity} available, {item.quantity} requested"
                        ]
                    }
                )

    def confirm_order(self):
        """Reserve inventory and confirm the order."""
        inventory_by_title = {inv.title: inv for inv in self.inventories}

        for item in self.order.items:
            inv = inventory_by_title[item.book_title]
            inv.reserve(item.quantity)

        self.order.confirm()
        return self.order


# --8<-- [end:service]


@domain.command(part_of=Order)
class ConfirmOrder:
    order_id: Identifier(required=True)


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

        # Persist changes
        repo.add(order)
        for inv in inventories:
            inv_repo.add(inv)


# --8<-- [end:handler]


domain.init(traverse=False)


# --8<-- [start:tests]
# tests/test_domain_services.py (example tests)


def test_confirm_order_with_stock():
    """Order is confirmed when inventory is sufficient."""
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
    assert inv.quantity == 8  # 10 - 2


def test_confirm_order_out_of_stock():
    """Order fails when inventory is insufficient."""
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
        assert False, "Should have raised ValidationError"
    except ValidationError as e:
        assert "Insufficient stock" in str(e.messages)


# --8<-- [end:tests]
# --8<-- [end:full]
