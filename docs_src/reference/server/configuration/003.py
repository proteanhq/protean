# The page shows bare dict literals of resolved configs.
# ruff: noqa: B018
from protean import Domain, handle
from protean.fields import Float, Identifier, String

domain = Domain(name="Shop")


@domain.aggregate
class Order:
    total: Float()


@domain.event(part_of=Order)
class OrderShipped:
    order_id: Identifier(required=True)


@domain.aggregate
class Notification:
    message: String()


@domain.aggregate
class Inventory:
    sku: String()


@domain.projection
class OrderSummary:
    order_id: Identifier(identifier=True)
    total: Float()


# --8<-- [start:production_handler]
@domain.event_handler(
    part_of=Order,
    subscription_profile="production",
    subscription_config={
        "messages_per_tick": 200,  # Higher throughput
    },
)
class OrderEventHandler: ...


# --8<-- [end:production_handler]

# --8<-- [start:production_resolved]
{
    "subscription_type": "stream",  # From profile
    "messages_per_tick": 200,  # From subscription_config (override)
    "blocking_timeout_ms": 5000,  # From profile
    "max_retries": 3,  # From profile
    "retry_delay_seconds": 1,  # From profile
    "enable_dlq": True,  # From profile
}
# --8<-- [end:production_resolved]


# --8<-- [start:fast_handler]
@domain.event_handler(
    part_of=Notification,
    subscription_profile="fast",
)
class NotificationEventHandler: ...


# --8<-- [end:fast_handler]

# --8<-- [start:fast_resolved]
{
    "subscription_type": "stream",
    "messages_per_tick": 10,
    "blocking_timeout_ms": 100,  # Short timeout for quick response
    "max_retries": 2,
    "retry_delay_seconds": 0,  # No delay between retries
    "enable_dlq": True,
}
# --8<-- [end:fast_resolved]


# --8<-- [start:projector]
@domain.projector(
    projector_for=OrderSummary,
    aggregates=[Order, Inventory],
    subscription_profile="projection",
)
class OrderSummaryProjector: ...


# --8<-- [end:projector]

# --8<-- [start:projector_resolved]
{
    "subscription_type": "event_store",  # Direct event store access
    "messages_per_tick": 100,
    "tick_interval": 0,
    "position_update_interval": 10,
    "enable_dlq": False,  # Not supported
}
# --8<-- [end:projector_resolved]


# --8<-- [start:origin_stream]
@domain.event_handler(
    part_of=Notification,
    stream_category="order",
    source_stream="user_actions",  # Only events from user_actions origin
    subscription_type="event_store",
)
class UserActionNotificationHandler:
    """Send notifications only for user-initiated order events."""

    @handle(OrderShipped)
    def notify_user(self, event):
        # Only called for OrderShipped events that originated from user_actions
        ...


# --8<-- [end:origin_stream]
