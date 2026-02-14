from enum import Enum

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, HasMany, Identifier, Integer, String, ValueObject

domain = Domain()


@domain.value_object
class Money:
    currency: String(max_length=3, default="USD")
    amount: Float(required=True)


class OrderStatus(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"


@domain.event(part_of="Order")
class OrderConfirmed:
    order_id: Identifier(required=True)
    customer_name: String(max_length=150, required=True)


@domain.aggregate
class Order:
    customer_name: String(max_length=150, required=True)
    payment_id: Identifier()
    status: String(
        max_length=20, choices=OrderStatus, default=OrderStatus.PENDING.value
    )
    items = HasMany("OrderItem")

    def confirm(self):
        self.status = OrderStatus.CONFIRMED.value
        self.raise_(OrderConfirmed(order_id=self.id, customer_name=self.customer_name))


@domain.entity(part_of=Order)
class OrderItem:
    book_title: String(max_length=200, required=True)
    quantity: Integer(required=True)
    unit_price = ValueObject(Money)


@domain.event(part_of="Inventory")
class StockReserved:
    book_id: Identifier(required=True)
    quantity: Integer(required=True)


@domain.aggregate
class Inventory:
    book_id: Identifier(required=True)
    title: String(max_length=200, required=True)
    quantity: Integer(default=0)

    def reserve_stock(self, amount: int):
        self.quantity -= amount
        self.raise_(StockReserved(book_id=self.book_id, quantity=amount))


# --8<-- [start:domain_service]
@domain.domain_service(part_of=[Order, Inventory])
class OrderFulfillmentService:
    def __init__(self, order, inventories):
        super().__init__(order, *inventories)
        self.order = order
        self.inventories = inventories

    def fulfill(self):
        """Check stock, reserve items, and confirm the order."""
        for item in self.order.items:
            inventory = next(
                (i for i in self.inventories if i.title == item.book_title),
                None,
            )
            inventory.reserve_stock(item.quantity)

        self.order.confirm()

    @invariant.pre
    def all_items_must_be_in_stock(self):
        for item in self.order.items:
            inventory = next(
                (i for i in self.inventories if i.title == item.book_title),
                None,
            )
            if inventory is None or inventory.quantity < item.quantity:
                raise ValidationError(
                    {"_service": [f"'{item.book_title}' is out of stock"]}
                )

    @invariant.pre
    def order_must_have_payment(self):
        if not self.order.payment_id:
            raise ValidationError(
                {"_service": ["Order must have a valid payment method"]}
            )


# --8<-- [end:domain_service]


domain.init(traverse=False)


# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        order_repo = domain.repository_for(Order)
        inventory_repo = domain.repository_for(Inventory)

        # Set up inventory
        inv1 = Inventory(book_id="book-1", title="The Great Gatsby", quantity=10)
        inv2 = Inventory(book_id="book-2", title="Brave New World", quantity=5)
        inventory_repo.add(inv1)
        inventory_repo.add(inv2)

        # Create an order
        order = Order(
            customer_name="Alice Johnson",
            payment_id="pay-123",
            items=[
                OrderItem(
                    book_title="The Great Gatsby",
                    quantity=2,
                    unit_price=Money(amount=12.99),
                ),
                OrderItem(
                    book_title="Brave New World",
                    quantity=1,
                    unit_price=Money(amount=14.99),
                ),
            ],
        )

        # Fulfill the order using the domain service
        print("=== Fulfilling Order ===")
        service = OrderFulfillmentService(order, [inv1, inv2])
        service.fulfill()

        print(f"Order status: {order.status}")
        print(f"Gatsby stock: {inv1.quantity}")
        print(f"Brave New World stock: {inv2.quantity}")

        # --- Pre-invariant: out of stock ---
        print("\n=== Out of Stock Scenario ===")
        big_order = Order(
            customer_name="Bob Smith",
            payment_id="pay-456",
            items=[
                OrderItem(
                    book_title="Brave New World",
                    quantity=100,  # More than available
                    unit_price=Money(amount=14.99),
                ),
            ],
        )
        try:
            OrderFulfillmentService(big_order, [inv2]).fulfill()
        except ValidationError as e:
            print(f"Caught: {e.messages}")

        # --- Pre-invariant: no payment ---
        print("\n=== Missing Payment Scenario ===")
        no_pay_order = Order(
            customer_name="Charlie",
            items=[
                OrderItem(
                    book_title="The Great Gatsby",
                    quantity=1,
                    unit_price=Money(amount=12.99),
                ),
            ],
        )
        try:
            OrderFulfillmentService(no_pay_order, [inv1]).fulfill()
        except ValidationError as e:
            print(f"Caught: {e.messages}")

        # Verify
        assert order.status == OrderStatus.CONFIRMED.value
        assert inv1.quantity == 8  # 10 - 2
        assert inv2.quantity == 4  # 5 - 1
        print("\nAll checks passed!")
# --8<-- [end:usage]
