from protean import Domain
from protean.fields import Float, Identifier

domain = Domain(name="Ordering")


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    total: Float(default=0.0)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)


# --8<-- [start:to_ir]
domain.init()
ir = domain.to_ir()
# --8<-- [end:to_ir]
