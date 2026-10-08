# --8<-- [start:config]
from protean import Domain

domain = Domain(
    name="Analytics",
    config={
        "brokers": {
            "default": {"provider": "inline"},
            "analytics": {"provider": "inline"},
        },
    },
)
# --8<-- [end:config]


# --8<-- [start:stream]
@domain.subscriber(stream="external_orders")
class ExternalOrderSubscriber:
    def __call__(self, payload: dict) -> None: ...


# --8<-- [end:stream]


# --8<-- [start:broker]
# Uses the default broker
@domain.subscriber(stream="order_events")
class OrderSubscriber:
    def __call__(self, payload: dict) -> None: ...


# Uses a specific named broker
@domain.subscriber(stream="analytics_events", broker="analytics")
class AnalyticsSubscriber:
    def __call__(self, payload: dict) -> None: ...


# --8<-- [end:broker]
