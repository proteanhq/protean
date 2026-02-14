from datetime import datetime, timezone

from protean import Domain, fields, invariant
from protean.exceptions import ValidationError
from pydantic import Field

domain = Domain()


@domain.event(part_of="Order")
class OrderConfirmed:
    order_id: str
    confirmed_at: datetime


@domain.event(part_of="Order")
class OrderDiscountApplied:
    order_id: str
    customer_id: str


@domain.aggregate
class Order:
    customer_id: str
    premium_customer: bool = False
    items = fields.HasMany("OrderItem")
    status: str = Field(
        default="PENDING",
        json_schema_extra={"choices": ["PENDING", "CONFIRMED", "SHIPPED", "DELIVERED"]},
    )
    payment_id: str | None = None

    @invariant.post
    def order_should_contain_items(self):
        if not self.items or len(self.items) == 0:
            raise ValidationError({"_entity": ["Order must contain at least one item"]})

    def confirm(self):
        self.status = "CONFIRMED"
        self.raise_(
            OrderConfirmed(order_id=self.id, confirmed_at=datetime.now(timezone.utc))
        )

        if self.premium_customer:
            self.raise_(
                OrderDiscountApplied(order_id=self.id, customer_id=self.customer_id)
            )


@domain.entity(part_of=Order)
class OrderItem:
    product_id: str
    quantity: int | None = None
    price: float | None = None
