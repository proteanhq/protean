from protean import Domain
from protean.fields import Auto, Float, Identifier, List, String

domain = Domain(name="DiscountCodes")


# --8<-- [start:problem]
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    discount_code: String()


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(required=True)
    total: Float(required=True)
    discount_code: String()  # New field


# --8<-- [end:problem]
