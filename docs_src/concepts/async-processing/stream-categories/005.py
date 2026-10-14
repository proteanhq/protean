from protean import Domain, handle
from protean.fields import Identifier

domain = Domain(name="ecommerce")


@domain.aggregate
class Order: ...


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)


# --8<-- [start:same_stream]
notified = []
counted = []


@domain.event_handler(part_of=Order)
class OrderNotificationHandler:
    # Subscription 1 to the "ecommerce::order" stream

    @handle(OrderPlaced)
    def notify(self, event):
        notified.append(event.order_id)


@domain.event_handler(part_of=Order)
class OrderAnalyticsHandler:
    # Subscription 2 to the "ecommerce::order" stream

    @handle(OrderPlaced)
    def count(self, event):
        counted.append(event.order_id)


# --8<-- [end:same_stream]
