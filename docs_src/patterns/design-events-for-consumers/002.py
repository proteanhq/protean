from protean import Domain
from protean.fields import Auto, Float, HasMany, Identifier, Integer, String

domain = Domain(name="FactEventOrders")


# --8<-- [start:fact_events]
@domain.entity(part_of="Order")
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(min_value=1, required=True)


@domain.aggregate(fact_events=True)
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    items = HasMany(OrderItem)
    status: String(default="draft")
    total: Float(default=0.0)


# --8<-- [end:fact_events]
