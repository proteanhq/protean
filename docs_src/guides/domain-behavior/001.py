# --8<-- [start:full]
from datetime import date, timedelta
from enum import Enum

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Date, Float, HasMany, Identifier, Integer, String

domain = Domain()


class OrderStatus(Enum):
    PENDING = "PENDING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


@domain.aggregate
class Order:
    customer_id: Identifier()
    order_date: Date()
    total_amount: Float()
    status: String(max_length=50, choices=OrderStatus)
    items = HasMany("OrderItem")

    @invariant.post
    def total_amount_of_order_must_equal_sum_of_subtotal_of_all_items(self):
        if self.total_amount != sum(item.subtotal for item in self.items):
            raise ValidationError({"_entity": ["Total should be sum of item prices"]})

    @invariant.post
    def order_date_must_be_within_the_last_30_days_if_status_is_pending(self):
        if (
            self.status == OrderStatus.PENDING.value
            and not date.today() - timedelta(days=30) <= self.order_date <= date.today()
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


@domain.entity(part_of=Order)
class OrderItem:
    product_id: Identifier()
    quantity: Integer()
    price: Float()
    subtotal: Float()

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


# --8<-- [end:full]


# --8<-- [start:atomic_change]
from protean import atomic_change


def add_third_item(order):
    with atomic_change(order):
        order.total_amount = 120.0
        order.add_items(
            OrderItem(product_id="3", quantity=2, price=10.0, subtotal=20.0)
        )


# --8<-- [end:atomic_change]


# --8<-- [start:codes]
def change_total(order):
    try:
        order.total_amount = 140.0
    except ValidationError as exc:
        print(exc.code)  # "INVARIANT_POST_FAILED"
        print(exc.codes)  # ["INVARIANT_POST_FAILED"]
        print(exc.fix)  # how to fix it, from the registry


# --8<-- [end:codes]
