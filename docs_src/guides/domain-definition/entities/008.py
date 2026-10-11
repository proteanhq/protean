from protean import Domain
from protean.fields import HasMany, Integer, String

domain = Domain()


# --8<-- [start:automatic_reference]
@domain.aggregate
class Order:
    number: String(max_length=20)
    items = HasMany("OrderItem")


@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(max_length=100)
    quantity: Integer()
    # Automatically gets: order = Reference(Order)
    # Automatically gets: order_id, a shadow field holding the order's id


# --8<-- [end:automatic_reference]
