from protean import Domain
from protean.fields import Identifier

domain = Domain(name="ecommerce")


@domain.aggregate
class Order: ...


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)


# --8<-- [start:same_stream]
@domain.event_handler(part_of=Order)
class OrderNotificationHandler:
    # Subscription 1 to "order" stream
    ...


@domain.event_handler(part_of=Order)
class OrderAnalyticsHandler:
    # Subscription 2 to "order" stream
    ...


# --8<-- [end:same_stream]
