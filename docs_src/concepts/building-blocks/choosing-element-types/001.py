from protean import Domain
from protean.fields import DateTime, Decimal, Integer, String, ValueObject

domain = Domain(name="ChoosingElementsShop")


# --8<-- [start:order]
from datetime import UTC, datetime


@domain.aggregate
class Order:
    order_number: String(max_length=20, required=True)
    customer_id: String(required=True)
    status: String(choices=["pending", "confirmed", "shipped"], default="pending")
    total_amount = ValueObject("Money")
    created_at: DateTime(default=lambda: datetime.now(UTC))


# --8<-- [end:order]


# --8<-- [start:order_item]
@domain.entity(part_of=Order)
class OrderItem:
    product_id: String(required=True)
    quantity: Integer(min_value=1, required=True)
    unit_price = ValueObject("Money")
    line_total = ValueObject("Money")


# --8<-- [end:order_item]


# --8<-- [start:money]
@domain.value_object
class Money:
    amount = Decimal(required=True, min_value=0)
    currency: String(max_length=3, required=True)

    def add(self, other):
        if self.currency != other.currency:
            raise ValueError("Cannot add different currencies")
        return Money(amount=self.amount + other.amount, currency=self.currency)


# --8<-- [end:money]


# --8<-- [start:entity_as_value_object]
# ❌ Bad: Treating entities like value objects
def process_order(order_item_data):
    # Creating new entity instead of referencing existing one
    item = OrderItem(**order_item_data)
    # Should retrieve existing entity by ID
    return item


# --8<-- [end:entity_as_value_object]
