from protean import Domain, handle

domain = Domain(name="ecommerce")


# --8<-- [start:handler]
@domain.aggregate
class Order: ...


@domain.event_handler(part_of=Order)
class OrderEventHandler:
    # Subscribes to Order's stream category ("order")
    ...


# --8<-- [end:handler]


# --8<-- [start:custom_category]
@domain.event_handler(part_of=Order, stream_category="all_orders")
class OrderReportHandler:
    # Subscribes to "all_orders" instead of Order's default

    @handle("$any")
    def record(self, event): ...


# --8<-- [end:custom_category]
