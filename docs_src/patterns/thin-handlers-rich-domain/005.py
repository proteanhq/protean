# --8<-- [start:application_service]
from protean import Domain, current_domain, use_case
from protean.core.application_service import BaseApplicationService
from protean.exceptions import ValidationError
from protean.fields import (
    Float,
    HasMany,
    Identifier,
    Integer,
    String,
    ValueObject,
)

domain = Domain(name="ThinHandlersOrdering")


@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, required=True)


@domain.entity(part_of="Order")
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(min_value=1, required=True)
    unit_price: Float(required=True)


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)


@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    customer_id: Identifier(required=True)
    items = HasMany(OrderItem)
    total = ValueObject(Money)
    status: String(default="draft")

    def add_item(self, product_id: str, quantity: int, unit_price: float) -> None:
        self.add_items(
            OrderItem(product_id=product_id, quantity=quantity, unit_price=unit_price)
        )

    def place(self) -> None:
        if not self.items:
            raise ValidationError({"items": ["Cannot place an order with no items"]})

        self.status = "placed"
        self.raise_(OrderPlaced(order_id=self.order_id, customer_id=self.customer_id))


@domain.application_service(part_of=Order)
class OrderApplicationService(BaseApplicationService):
    @use_case
    def place_order(self, order_id, customer_id, items, total, currency):
        repo = current_domain.repository_for(Order)
        order = Order(
            order_id=order_id,
            customer_id=customer_id,
            total=Money(amount=total, currency=currency),
        )
        for item in items:
            order.add_item(**item)
        order.place()
        repo.add(order)


# --8<-- [end:application_service]
