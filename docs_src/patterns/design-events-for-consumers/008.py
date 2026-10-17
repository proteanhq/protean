from protean import Domain
from protean.fields import Auto, DateTime, Float, Identifier, List, String

# --8<-- [start:published_event]
# In the Order domain: event published to the broker
domain = Domain(name="Ordering")


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    customer_email: String(required=True)
    items: List(required=True)
    total: Float(required=True)
    currency: String(required=True)
    placed_at: DateTime(required=True)


# --8<-- [end:published_event]
