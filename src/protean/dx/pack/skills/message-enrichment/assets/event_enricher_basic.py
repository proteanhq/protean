"""
Event enricher: attach tenant + aggregate context to every event.

This example demonstrates:
- Registering an event enricher with @domain.event_enricher
- The enricher signature: def fn(event, aggregate) -> dict (it also gets the aggregate)
- Reading from g and from aggregate state, returning data for metadata.extensions
- Safe context access with getattr(..., None)

Usage:
    g.tenant_id = "acme"
    order.place()  # raises OrderPlaced; enricher merges tenant + aggregate_type
"""

from protean import Domain
from protean.fields import Identifier, String
from protean.utils.globals import g

# Domain setup
domain = Domain()


@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    customer_id: Identifier(required=True)
    status: String(default="draft")

    def place(self):
        self.status = "placed"
        self.raise_(OrderPlaced(order_id=self.order_id, customer_id=self.customer_id))


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)


@domain.event_enricher
def add_event_context(event, aggregate):
    """Merge tenant context and the raising aggregate's type into extensions."""
    return {
        "tenant_id": getattr(g, "tenant_id", None),
        "aggregate_type": type(aggregate).__name__,
    }


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        g.tenant_id = "acme"
        order = Order(order_id="ORD-1", customer_id="CUST-1")
        order.place()
        print("event raised; tenant + aggregate_type merged into extensions")
