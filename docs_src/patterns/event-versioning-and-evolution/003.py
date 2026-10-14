from protean import Domain
from protean.fields import Auto, Float, Identifier, List, String

domain = Domain(name="OrderEventsAfter")


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)


# --8<-- [start:after]
# After: added discount_code and channel (same message version, no bump)
@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(required=True)
    total: Float(required=True)
    discount_code: String(default=None)  # New, optional
    channel: String(default="web")  # New, with sensible default


# --8<-- [end:after]


# --8<-- [start:new_type]
# New business operation: gift wrapping
@domain.event(part_of=Order)
class OrderGiftWrapped:
    order_id: Identifier(required=True)
    wrapping_style: String(required=True)
    gift_message: String()


# --8<-- [end:new_type]
