from protean import Domain, handle
from protean.fields import Auto, Float, Identifier, List, String
from protean.utils.globals import current_domain

domain = Domain(name="NewEventType")


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)


# --8<-- [start:event_types]
# Original event (keep for historical data)
@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(required=True)
    total: Float(required=True)


# New event for the updated business process
@domain.event(part_of=Order)
class OrderPlacedV2:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    line_items: List(required=True)  # Renamed from 'items'
    subtotal: Float(required=True)  # Changed semantics
    tax: Float(required=True)  # New required field
    total: Float(required=True)
    currency: String(required=True)  # New required field


# --8<-- [end:event_types]


# --8<-- [start:handler]
@domain.aggregate
class Fulfillment:
    order_id: Identifier(required=True)
    items: List()
    total: Float()
    currency: String()


@domain.event_handler(part_of=Fulfillment, stream_category=Order.meta_.stream_category)
class FulfillmentEventHandler:
    @handle(OrderPlaced)
    def on_order_placed_v1(self, event: OrderPlaced):
        """Handle historical events."""
        self._create_fulfillment(
            order_id=event.order_id,
            items=event.items,
            total=event.total,
            currency="USD",  # Assumed for v1 events
        )

    @handle(OrderPlacedV2)
    def on_order_placed_v2(self, event: OrderPlacedV2):
        """Handle current events."""
        self._create_fulfillment(
            order_id=event.order_id,
            items=event.line_items,
            total=event.total,
            currency=event.currency,
        )

    def _create_fulfillment(self, order_id, items, total, currency):
        # Shared implementation
        repo = current_domain.repository_for(Fulfillment)
        fulfillment = Fulfillment(
            order_id=order_id,
            items=items,
            total=total,
            currency=currency,
        )
        repo.add(fulfillment)


# --8<-- [end:handler]
