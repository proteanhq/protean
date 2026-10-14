from protean import Domain, handle
from protean.fields import Identifier

domain = Domain(name="ecommerce")


@domain.aggregate
class Order: ...


# --8<-- [start:default_handler]
@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)


@domain.event_handler(part_of=Order)
class OrderEventHandler:
    # Subscribes to Order's stream category ("order")

    @handle(OrderPlaced)
    def handle_order_placed(self, event): ...


# --8<-- [end:default_handler]


# --8<-- [start:explicit_handler]
@domain.event_handler(part_of=Order, stream_category="all_orders")
class OrderReportHandler:
    # Subscribes to "all_orders" instead of Order's default

    @handle("$any")
    def record(self, event): ...


# --8<-- [end:explicit_handler]
