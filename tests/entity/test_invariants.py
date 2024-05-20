from protean import BaseAggregate, BaseEntity, invariant
from protean.exceptions import ValidationError
from protean.fields import Date, Float, Integer, String, HasMany


class Order(BaseAggregate):
    ordered_on = Date()
    total = Float()
    items = HasMany("OrderItem")

    @invariant
    def total_should_be_sum_of_item_prices(self):
        if self.items:
            if self.total != sum([item.price for item in self.items]):
                raise ValidationError("Total should be sum of item prices")

    @invariant
    def must_have_at_least_one_item(self):
        if not self.items or len(self.items) == 0:
            raise ValidationError("Order must contain at least one item")

    @invariant
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

    @invariant
    def price_should_be_non_negative(self):
        if self.price < 0:
            raise ValidationError("Item price should be non-negative")


def test_that_entity_has_recorded_invariants(test_domain):
    test_domain.register(OrderItem)
    test_domain.register(Order)
    test_domain.init(traverse=False)

    assert len(Order._invariants) == 3
    # Methods are presented in ascending order (alphabetical order) of member names.
    assert Order._invariants[0].__name__ == "item_quantities_should_be_positive"
    assert Order._invariants[1].__name__ == "must_have_at_least_one_item"
    assert Order._invariants[2].__name__ == "total_should_be_sum_of_item_prices"

    assert len(OrderItem._invariants) == 1
    assert OrderItem._invariants[0].__name__ == "price_should_be_non_negative"
