import pytest

from protean import Domain
from protean.fields import Float, HasMany, Integer

domain = Domain(name="Ordering")


@domain.aggregate
class Order:
    lines = HasMany("OrderLine")

    def add_line(self, price, quantity):
        self.add_lines(OrderLine(price=price, quantity=quantity))

    @property
    def total(self):
        return sum(line.price * line.quantity for line in self.lines)


@domain.entity(part_of=Order)
class OrderLine:
    price = Float(required=True)
    quantity = Integer(required=True)


@pytest.fixture(scope="module", autouse=True)
def ordering():
    domain.init(traverse=False)
    with domain.domain_context():
        yield


# --8<-- [start:exact_value]
def test_the_total_adds_price_times_quantity_for_each_line():
    order = Order()
    order.add_line(price=10.0, quantity=2)
    order.add_line(price=5.0, quantity=3)

    assert order.total == 35.0


# --8<-- [end:exact_value]
