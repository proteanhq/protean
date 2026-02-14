from protean import Domain
from protean.fields import String, Integer, Float, HasMany

domain = Domain()


@domain.entity(part_of="Order")
class LineItem:
    description: String(max_length=200, required=True)
    quantity: Integer(min_value=1, default=1)
    unit_price: Float(min_value=0)


@domain.aggregate
class Order:
    customer_name: String(max_length=100, required=True)
    items = HasMany("LineItem")
