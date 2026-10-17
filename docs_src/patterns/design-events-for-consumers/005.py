from protean import Domain
from protean.fields import Auto, DateTime, Float, Identifier, List, String

domain = Domain(name="ConsumerFields")


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)


# --8<-- [start:consumer_fields]
# Notification handler needs: customer_email, customer_name, order summary
# Projector needs: order details for the read model
# Loyalty handler needs: customer_id, total (to calculate points)
# Analytics handler needs: items, total, placed_at (for reporting)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    customer_name: String(required=True)  # For notifications
    customer_email: String(required=True)  # For notifications
    items: List(required=True)  # For projections, analytics
    total: Float(required=True)  # For loyalty, analytics
    placed_at: DateTime(required=True)  # For analytics, projections


# --8<-- [end:consumer_fields]
