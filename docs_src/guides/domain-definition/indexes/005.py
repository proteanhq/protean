from protean import Domain, Index
from protean.fields import HasMany, Integer, String

domain = Domain(name="Ordering")


# --8<-- [start:entity]
@domain.aggregate
class Order:
    customer_id = String(max_length=64)
    items = HasMany("LineItem")


@domain.entity(part_of=Order, indexes=[Index("sku", unique=True)])
class LineItem:
    sku = String(max_length=64)
    quantity = Integer()


# --8<-- [end:entity]
