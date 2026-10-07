from protean import Domain
from protean.fields import DateTime, HasMany, Integer, Reference

domain = Domain(name="Ordering")


# --8<-- [start:order_item]
@domain.entity(part_of="Order")
class OrderItem:
    quantity: Integer()
    order = Reference("Order", referenced_as="order_number")
    # Creates shadow field 'order_number' instead of 'order_id'


# --8<-- [end:order_item]


# --8<-- [start:order]
@domain.aggregate
class Order:
    ordered_at: DateTime()
    items = HasMany(OrderItem, via="order_number")


# --8<-- [end:order]
