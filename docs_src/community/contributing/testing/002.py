from protean import Domain
from protean.fields import Identifier, String

domain = Domain(name="Ordering")


# --8<-- [start:place_order]
@domain.aggregate
class Order:
    status = String()


@domain.command(part_of=Order)
class PlaceOrder:
    order_id = Identifier(required=True)


# --8<-- [end:place_order]
