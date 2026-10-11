from protean import Domain
from protean.fields import HasMany, Integer, String

domain = Domain()


# --8<-- [start:indexes]
from protean import Index


@domain.aggregate
class Order:
    number: String(max_length=20)
    line_items = HasMany("LineItem")


@domain.entity(part_of=Order, indexes=[Index("sku", unique=True)])
class LineItem:
    sku = String(max_length=64)
    quantity = Integer()


# --8<-- [end:indexes]
