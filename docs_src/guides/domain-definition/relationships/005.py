from protean import Domain
from protean.fields import HasMany, Reference, String

domain = Domain(name="Ordering")


# --8<-- [start:entity]
@domain.aggregate
class Order:
    items = HasMany("OrderItem", via="order_number")


@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(max_length=100)
    order = Reference(Order, referenced_as="order_number")
    # Creates shadow field named 'order_number' instead of 'order_id'


# --8<-- [end:entity]
