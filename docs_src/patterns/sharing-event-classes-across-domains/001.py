from protean import Domain
from protean.fields import Auto, DateTime, Float, Identifier, List, String

domain = Domain(name="SubsetConsumption")


# --8<-- [start:subset]
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)


@domain.aggregate
class Shipment:
    shipment_id: Auto(identifier=True)


# Order domain publishes this
@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    customer_email: String(required=True)
    items: List(required=True)
    subtotal: Float(required=True)
    tax: Float(required=True)
    total: Float(required=True)
    currency: String(required=True)
    discount_code: String()
    placed_at: DateTime(required=True)
    ip_address: String()
    user_agent: String()


# Fulfillment domain only needs this
@domain.event(part_of=Shipment)
class ExternalOrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(required=True)


# --8<-- [end:subset]
