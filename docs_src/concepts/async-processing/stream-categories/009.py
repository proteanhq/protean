from protean import Domain

domain = Domain(name="ecommerce")


# --8<-- [start:single_handler]
@domain.aggregate
class Order: ...


@domain.event_handler(part_of=Order)
class OrderEventHandler:
    # Subscribes to Order's stream category
    ...


# --8<-- [end:single_handler]
