from enum import Enum
from datetime import date

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Date, Float, Identifier, Integer, String, HasMany

domain = Domain(__file__, load_toml=False)


class OrderStatus(Enum):
    PENDING = "PENDING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


@domain.aggregate
class Order:
    customer_id = Identifier()
    order_date = Date()
    total_amount = Float()
    status = String(max_length=50, choices=OrderStatus)
    items = HasMany("OrderItem")

    @invariant.post
    def total_amount_of_order_must_equal_sum_of_subtotal_of_all_items(self):
        if self.total_amount != sum(item.subtotal for item in self.items):
            raise ValidationError({"_entity": ["Total should be sum of item prices"]})

    @invariant.post
    def order_date_must_be_within_the_last_30_days_if_status_is_pending(self):
        if self.status == OrderStatus.PENDING.value and self.order_date < date(
            2020, 1, 1
        ):
            raise ValidationError(
                {
                    "_entity": [
                        "Order date must be within the last 30 days if status is PENDING"
                    ]
                }
            )

    @invariant.post
    def customer_id_must_be_non_null_and_the_order_must_contain_at_least_one_item(self):
        if not self.customer_id or not self.items:
            raise ValidationError(
                {
                    "_entity": [
                        "Customer ID must be non-null and the order must contain at least one item"
                    ]
                }
            )


@domain.entity
class OrderItem:
    product_id = Identifier()
    quantity = Integer()
    price = Float()
    subtotal = Float()

    class Meta:
        part_of = Order

    @invariant.post
    def the_quantity_must_be_a_positive_integer_and_the_subtotal_must_be_correctly_calculated(
        self,
    ):
        if self.quantity <= 0 or self.subtotal != self.quantity * self.price:
            raise ValidationError(
                {
                    "_entity": [
                        "Quantity must be a positive integer and the subtotal must be correctly calculated"
                    ]
                }
            )
