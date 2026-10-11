from protean import Domain
from protean.fields import Integer, String

domain = Domain(name="Ordering")


# --8<-- [start:value_object_list]
from protean.fields import List, ValueObject


@domain.value_object
class OrderItem:
    sku = String(required=True)
    quantity = Integer(default=1)


@domain.aggregate
class Order:
    items = List(content_type=ValueObject(OrderItem))


# --8<-- [end:value_object_list]
