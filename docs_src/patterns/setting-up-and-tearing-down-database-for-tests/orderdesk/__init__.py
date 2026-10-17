from protean import Domain
from protean.fields import Float, Identifier

domain = Domain(name="OrderDesk")


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    total: Float(min_value=0.0)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
