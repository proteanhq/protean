from datetime import datetime
from enum import Enum

from protean import BaseAggregate, BaseEntity, invariant
from protean.exceptions import ValidationError
from protean.fields import Date, Float, Integer, String, HasMany


class OrderStatus(Enum):
    PENDING = "PENDING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


class Order(BaseAggregate):
    ordered_on = Date()
    total = Float()
    items = HasMany("OrderItem")
    status = String(
        max_length=50, choices=OrderStatus, default=OrderStatus.PENDING.value
    )

    @invariant.pre
    def order_date_must_be_in_the_past_and_status_pending_to_update_order(self):
        if (
            self.status != OrderStatus.PENDING.value
            or self.order_date >= datetime.today().date()
        ):
            raise ValidationError(
                {
                    "_entity": [
                        "Order date must be in the past and status PENDING to update order"
                    ]
                }
            )

    @invariant.post
    def total_should_be_sum_of_item_prices(self):
        if self.items:
            if self.total != sum([item.price for item in self.items]):
                raise ValidationError("Total should be sum of item prices")

    @invariant.post
    def must_have_at_least_one_item(self):
        if not self.items or len(self.items) == 0:
            raise ValidationError("Order must contain at least one item")

    @invariant.post
    def item_quantities_should_be_positive(self):
        for item in self.items:
            if item.quantity <= 0:
                raise ValidationError("Item quantities should be positive")


class OrderItem(BaseEntity):
    product_id = String(max_length=50)
    quantity = Integer()
    price = Float()

    class Meta:
        part_of = Order

    @invariant.post
    def price_should_be_non_negative(self):
        if self.price < 0:
            raise ValidationError("Item price should be non-negative")


def test_that_entity_has_recorded_invariants(test_domain):
    test_domain.register(OrderItem)
    test_domain.register(Order)
    test_domain.init(traverse=False)

    assert len(Order._invariants["pre"]) == 1
    assert len(Order._invariants["post"]) == 3

    assert (
        "order_date_must_be_in_the_past_and_status_pending_to_update_order"
        in Order._invariants["pre"]
    )
    # Methods are presented in ascending order (alphabetical order) of member names.
    assert "item_quantities_should_be_positive" in Order._invariants["post"]
    assert "must_have_at_least_one_item" in Order._invariants["post"]
    assert "total_should_be_sum_of_item_prices" in Order._invariants["post"]

    assert len(OrderItem._invariants["post"]) == 1
    assert "price_should_be_non_negative" in OrderItem._invariants["post"]
