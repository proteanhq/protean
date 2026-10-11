from protean import Domain
from protean.fields import Decimal, HasMany, Integer, String

domain = Domain()


@domain.aggregate
class Order:
    number: String(max_length=20)
    line_items = HasMany("ProductLineItem")


# --8<-- [start:base_class]
from protean.core.entity import BaseEntity
from protean.utils.reflection import declared_fields


class BaseLineItem(BaseEntity):
    quantity: Integer(required=True, min_value=1)
    unit_price: Decimal(precision=19, scale=4, required=True)

    @property
    def subtotal(self):
        return self.quantity * self.unit_price


@domain.entity(part_of=Order)
class ProductLineItem(BaseLineItem):
    sku: String(max_length=64, required=True)


print(list(declared_fields(ProductLineItem)))
# ['quantity', 'unit_price', 'id', 'sku', 'order']
# --8<-- [end:base_class]
