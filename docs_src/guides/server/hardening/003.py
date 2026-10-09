from protean import Domain

# --8<-- [start:imports]
from protean.core.event_handler import BaseEventHandler
from protean.fields import String

# --8<-- [end:imports]
# --8<-- [start:profile-imports]
from protean.server.subscription.profiles import SubscriptionProfile

# --8<-- [end:profile-imports]

domain = Domain(name="Orders")


# --8<-- [start:order]
@domain.aggregate
class Order:
    status = String(default="PLACED")


# --8<-- [end:order]


# --8<-- [start:audit]
@domain.event_handler(
    part_of=Order,
    subscription_config={
        "dlq_retention_hours": 720,
        "dlq_alert_threshold": 10,
    },
)
class AuditHandler(BaseEventHandler): ...


# --8<-- [end:audit]


# --8<-- [start:profile]
@domain.event_handler(
    part_of=Order,
    subscription_profile=SubscriptionProfile.PRODUCTION,
)
class OrderEventHandler(BaseEventHandler): ...


# --8<-- [end:profile]


# --8<-- [start:override]
@domain.event_handler(
    part_of=Order,
    subscription_profile=SubscriptionProfile.PRODUCTION,
    subscription_config={"messages_per_tick": 50},
)
class BulkOrderHandler(BaseEventHandler): ...


# --8<-- [end:override]
