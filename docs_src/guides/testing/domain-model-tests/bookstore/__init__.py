# --8<-- [start:domain]
from protean import Domain, atomic_change, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, HasMany, Identifier, Integer, String, Text

domain = Domain(name="Bookstore")


@domain.event(part_of="Book")
class BookPublished:
    book_id: Identifier(required=True)


@domain.aggregate
class Book:
    title: String(max_length=200, required=True)
    author: String(max_length=100, required=True)
    body: Text()
    status: String(max_length=20, default="DRAFT")

    def publish(self):
        self.status = "PUBLISHED"
        self.raise_(BookPublished(book_id=self.id))


@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

    def add(self, other):
        if other.currency != self.currency:
            raise ValidationError({"currency": ["Cannot add different currencies"]})
        return Money(
            amount=round(self.amount + other.amount, 2), currency=self.currency
        )


@domain.entity(part_of="Order")
class OrderItem:
    product_id: String(max_length=50, required=True)
    quantity: Integer(min_value=1, required=True)
    price: Float(default=0.0)
    subtotal: Float(default=0.0)


@domain.aggregate
class Order:
    customer_name: String(max_length=100, required=True)
    total_amount: Float(default=0.0)
    status: String(max_length=20, default="PENDING")
    items = HasMany(OrderItem)

    @invariant.post
    def total_should_be_sum_of_item_prices(self):
        if self.total_amount != sum(i.subtotal for i in self.items):
            raise ValidationError({"_entity": ["Total should be sum of item prices"]})

    @invariant.pre
    def shipped_orders_cannot_change(self):
        if self.status == "SHIPPED":
            raise ValidationError({"_entity": ["A shipped order cannot be changed"]})

    def add_item(self, product_id, quantity, price):
        with atomic_change(self):
            self.add_items(
                OrderItem(
                    product_id=product_id,
                    quantity=quantity,
                    price=price,
                    subtotal=quantity * price,
                )
            )
            self.total_amount = sum(i.subtotal for i in self.items)

    def cancel_item(self, product_id):
        item = next(i for i in self.items if i.product_id == product_id)
        with atomic_change(self):
            self.remove_items(item)
            self.total_amount = sum(i.subtotal for i in self.items)


@domain.aggregate
class Inventory:
    product_id: String(max_length=50, required=True)
    title: String(max_length=200, required=True)
    quantity: Integer(default=0)


@domain.domain_service(part_of=[Order, Inventory])
class OrderFulfillmentService:
    def __init__(self, order, inventories):
        super().__init__(order, *inventories)
        self.order = order
        self.inventories = {inv.product_id: inv for inv in inventories}

    @invariant.pre
    def every_item_should_be_in_stock(self):
        for item in self.order.items:
            stock = self.inventories.get(item.product_id)
            if stock is None or stock.quantity < item.quantity:
                raise ValidationError(
                    {"_service": [f"Insufficient stock for {item.product_id}"]}
                )

    def confirm_order(self):
        self.order.status = "CONFIRMED"


# --8<-- [end:domain]
