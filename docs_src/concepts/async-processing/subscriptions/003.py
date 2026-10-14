from protean import Domain

domain = Domain(name="ecommerce")


# --8<-- [start:default_category]
@domain.aggregate
class Order: ...  # Stream category: "order"


@domain.event_handler(part_of=Order)
class OrderEventHandler:
    # Automatically subscribes to "order" stream category
    ...


# --8<-- [end:default_category]
