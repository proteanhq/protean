from protean import Domain, apply
from protean.fields import Float, Identifier, List, String

domain = Domain(name="ReplayWithoutUpcasting")


@domain.event(part_of="Order")
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    items = List(required=True)
    total = Float(required=True)


@domain.event(part_of="Order")
class OrderPlacedV2:
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    line_items = List(required=True)
    subtotal = Float(required=True)
    tax = Float(required=True)
    total = Float(required=True)
    currency = String(required=True)


# --8<-- [start:aggregate]
@domain.aggregate(event_sourced=True)
class Order:
    order_id = Identifier(identifier=True)
    customer_id = Identifier()
    items = List()
    total = Float()
    currency = String()

    @apply
    def on_order_placed(self, event: OrderPlaced):
        self.order_id = event.order_id
        self.customer_id = event.customer_id
        self.items = event.items
        self.total = event.total
        self.currency = getattr(event, "currency", "USD")

    @apply
    def on_order_placed_v2(self, event: OrderPlacedV2):
        self.order_id = event.order_id
        self.customer_id = event.customer_id
        self.items = event.line_items
        self.total = event.total
        self.currency = event.currency


# --8<-- [end:aggregate]
