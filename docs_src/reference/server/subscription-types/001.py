from protean import Domain, current_domain
from protean.fields import Float, Identifier

domain = Domain(name="Shop")


# --8<-- [start:model]
@domain.aggregate
class Order:
    total: Float(required=True)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    total: Float(required=True)


# --8<-- [end:model]


# Each example below reuses the name the page gives it, so a later one replaces
# the earlier one in the registry. The aliases keep each class for the tests.
# --8<-- [start:retries]
@domain.event_handler(
    part_of=Order,
    subscription_type="stream",
    subscription_config={
        "max_retries": 3,
        "retry_delay_seconds": 1,
    },
)
class OrderEventHandler: ...


# --8<-- [end:retries]
RetryingHandler = OrderEventHandler


# --8<-- [start:origin_filter]
@domain.event_handler(
    part_of=Order,
    source_stream="manage_order",  # Only events triggered by manage_order commands
)
class OrderEventHandler: ...


# --8<-- [end:origin_filter]
OriginFilteredHandler = OrderEventHandler


# --8<-- [start:stream_config]
@domain.event_handler(
    part_of=Order,
    subscription_type="stream",
    subscription_config={
        "messages_per_tick": 100,
        "blocking_timeout_ms": 5000,
        "max_retries": 3,
        "retry_delay_seconds": 1,
        "enable_dlq": True,
    },
)
class OrderEventHandler: ...


# --8<-- [end:stream_config]
StreamHandler = OrderEventHandler


# --8<-- [start:stream_profile]
@domain.event_handler(
    part_of=Order,
    subscription_profile="production",
)
class OrderEventHandler: ...


# --8<-- [end:stream_profile]
ProductionHandler = OrderEventHandler


# --8<-- [start:event_store_config]
@domain.event_handler(
    part_of=Order,
    subscription_type="event_store",
    subscription_config={
        "messages_per_tick": 100,
        "tick_interval": 1,
        "position_update_interval": 10,
    },
)
class OrderEventHandler: ...


# --8<-- [end:event_store_config]
EventStoreHandler = OrderEventHandler


# --8<-- [start:projection_profile]
@domain.projection
class OrderSummary:
    order_id: Identifier(identifier=True)
    total: Float()


@domain.projector(
    projector_for=OrderSummary,
    aggregates=[Order],
    subscription_profile="projection",
)
class OrderProjector: ...


# --8<-- [end:projection_profile]


def place_order(total: float) -> Order:
    order = Order(total=total)
    order.raise_(OrderPlaced(order_id=order.id, total=total))
    current_domain.repository_for(Order).add(order)
    return order
