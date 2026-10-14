from protean import Domain
from protean.fields import Identifier

domain = Domain(name="CommandsConcept")


# --8<-- [start:versioned]
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)


@domain.command(part_of=Order)
class PlaceOrder:
    __version__ = 2

    customer_id: Identifier(required=True)


# --8<-- [end:versioned]


@domain.command(part_of=Order)
class CancelOrder:
    order_id: Identifier(required=True)
