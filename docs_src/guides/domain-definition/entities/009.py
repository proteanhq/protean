from protean import Domain
from protean.fields import HasMany, Integer, Reference, String

domain = Domain()


# --8<-- [start:explicit_reference]
@domain.aggregate
class Order:
    number: String(max_length=20)
    items = HasMany("OrderItem", via="parent_order_id")


@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(max_length=100)
    quantity: Integer()
    order = Reference(Order, referenced_as="parent_order_id")
    # Creates shadow field 'parent_order_id' instead of 'order_id'


# --8<-- [end:explicit_reference]
