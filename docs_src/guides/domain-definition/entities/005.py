from protean import Domain
from protean.fields import Decimal, HasMany, Integer, String

domain = Domain()


@domain.aggregate
class Order:
    number: String(max_length=20)
    items = HasMany("OrderItem")


# --8<-- [start:defaults]
@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(max_length=100)
    quantity: Integer(default=1)
    unit_price: Decimal(precision=19, scale=4)
    line_total: Decimal(precision=19, scale=4)

    def defaults(self):
        if self.line_total is None and self.unit_price is not None:
            self.line_total = self.quantity * self.unit_price


# --8<-- [end:defaults]
