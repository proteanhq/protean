from protean import Domain
from protean.fields import String

domain = Domain(name="Ordering")


# --8<-- [start:version]
@domain.aggregate
class Order:
    status = String()


@domain.event(part_of=Order, version=2)  # decorator option
class OrderPlaced:
    order_id = String()


@domain.event(part_of=Order)
class OrderShipped:
    __version__ = 2  # class attribute
    order_id = String()


# --8<-- [end:version]
