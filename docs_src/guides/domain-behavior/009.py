from datetime import datetime, timezone

from protean import Domain, fields, invariant
from protean.exceptions import ValidationError

domain = Domain(__file__)


@domain.event(part_of="Order")
class OrderConfirmed:
    order_id = fields.Identifier(required=True)
    confirmed_at = fields.DateTime(required=True)


@domain.event(part_of="Order")
class OrderDiscountApplied:
    order_id = fields.Identifier(required=True)
    customer_id = fields.Identifier(required=True)


@domain.aggregate
class Order:
    customer_id = fields.Identifier(required=True)
    premium_customer = fields.Boolean(default=False)
    items = fields.HasMany("OrderItem")
    status = fields.String(
        choices=["PENDING", "CONFIRMED", "SHIPPED", "DELIVERED"], default="PENDING"
    )
    payment_id = fields.Identifier()

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
    product_id = fields.Identifier(required=True)
    quantity = fields.Integer()
    price = fields.Float()
