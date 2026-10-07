# --8<-- [start:full]
# --8<-- [start:subscriber]
from protean import Domain
from protean.exceptions import ValidationError

domain = Domain(name="Messaging")
domain.config["brokers"]["notifications"] = {"provider": "inline"}

# Deliver to subscribers as soon as a message is published
domain.config["message_processing"] = "sync"

welcomed = []


@domain.subscriber(stream="user-events")
class UserEventSubscriber:
    def __call__(self, payload: dict) -> None:
        # A subscriber receives the raw message dict
        if payload["event_type"] == "user.registered":
            welcomed.append(payload["email"])
            # Send welcome email...


domain.init(traverse=False)
# --8<-- [end:subscriber]

# --8<-- [start:publish]
with domain.domain_context():
    # Publish to the default broker
    domain.brokers.publish(
        stream="user-events",
        message={
            "event_type": "user.registered",
            "user_id": "123",
            "email": "user@example.com",
        },
    )

    # Publish to a specific broker
    domain.brokers["notifications"].publish(
        stream="notifications",
        message={
            "type": "email",
            "to": "user@example.com",
            "subject": "Welcome!",
        },
    )
# --8<-- [end:publish]

# --8<-- [start:errors]
with domain.domain_context():
    try:
        domain.brokers.publish(stream="events", message={})
    except ValidationError as exc:
        # An empty message is rejected before it reaches the broker
        error = exc.messages
# --8<-- [end:errors]

# --8<-- [start:health]
with domain.domain_context():
    # Check broker connection
    broker = domain.brokers["default"]
    if broker.ping():
        print("Broker is healthy")

    # Get detailed health statistics
    health_stats = broker.health_stats()
    print(f"Status: {health_stats['status']}")  # healthy, degraded or unhealthy
    print(f"Connected: {health_stats['connected']}")
    print(f"Details: {health_stats['details']}")  # broker-specific
# --8<-- [end:health]
# --8<-- [end:full]
