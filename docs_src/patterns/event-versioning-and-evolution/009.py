from protean import Domain, handle
from protean.fields import Auto, Boolean, Float, Identifier, List, String
from protean.utils.globals import current_domain

domain = Domain(name="TolerantReader")


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(required=True)
    total: Float(required=True)
    discount_code: String(default=None)


# --8<-- [start:handler]
@domain.aggregate
class Analytics:
    order_id: Identifier(required=True)
    total: Float()
    channel: String()
    has_discount: Boolean()
    currency: String()


@domain.event_handler(part_of=Analytics, stream_category=Order.meta_.stream_category)
class AnalyticsEventHandler:
    @handle(OrderPlaced)
    def track_order(self, event: OrderPlaced):
        # Use getattr with defaults for fields that may not exist
        channel = getattr(event, "channel", "unknown")
        discount = getattr(event, "discount_code", None)
        currency = getattr(event, "currency", "USD")

        self._record_analytics(
            order_id=event.order_id,
            total=event.total,
            channel=channel,
            has_discount=discount is not None,
            currency=currency,
        )

    # --8<-- [end:handler]

    def _record_analytics(self, **values):
        current_domain.repository_for(Analytics).add(Analytics(**values))
