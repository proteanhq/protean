from protean import Domain
from protean.fields import Auto, Identifier, String

domain = Domain(name="RenameBefore")


@domain.aggregate
class Order:
    order_id = Auto(identifier=True)


# --8<-- [start:before]
# Before
@domain.event(part_of=Order)
class OrderPlaced:
    order_id = Identifier(required=True)
    name = String(required=True)


# --8<-- [end:before]
