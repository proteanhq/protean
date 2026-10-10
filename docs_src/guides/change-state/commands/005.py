from protean import Domain
from protean.fields import List, String

domain = Domain(name="Sales")


@domain.aggregate
class Order:
    items: List(content_type=String)


# --8<-- [start:handler_timeout]
# Per-handler default (seconds or a timedelta)
@domain.command_handler(part_of=Order, timeout=30)
class OrderCommandHandler: ...


# --8<-- [end:handler_timeout]
