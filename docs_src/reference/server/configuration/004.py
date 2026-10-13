# The page shows bare dict literals of resolved configs.
# ruff: noqa: B018
from protean import Domain
from protean.fields import Float

domain = Domain(name="Shop")


@domain.aggregate
class Order:
    total: Float()


# --8<-- [start:special_handler]
@domain.event_handler(
    part_of=Order,
    subscription_config={
        "enable_dlq": False,  # Highest priority - overrides everything
    },
)
class SpecialHandler: ...


# --8<-- [end:special_handler]

# --8<-- [start:special_resolved]
{
    "subscription_type": "stream",  # From profile (via server.subscriptions.SpecialHandler)
    "messages_per_tick": 500,  # From server.subscriptions.SpecialHandler
    "max_retries": 10,  # From server.subscriptions.SpecialHandler
    "enable_dlq": False,  # From handler subscription_config (override)
    "blocking_timeout_ms": 5000,  # From profile
    "retry_delay_seconds": 1,  # From profile
}
# --8<-- [end:special_resolved]
