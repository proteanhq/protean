from protean import Domain
from protean.fields import Auto, DateTime, Identifier, String

domain = Domain(name="MyApp")


# --8<-- [start:published_event]
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)


@domain.event(part_of=Order, published=True)
class OrderShipped:
    order_id: Identifier(required=True)
    shipped_at: DateTime(required=True)
    tracking_number: String(max_length=50)


# --8<-- [end:published_event]
