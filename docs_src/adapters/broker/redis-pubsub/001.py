# --8<-- [start:full]
# --8<-- [start:setup]
import os

from protean import Domain

domain = Domain(name="Notifications")
domain.config["brokers"]["notifications"] = {
    "provider": "redis_pubsub",
    "URI": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
}

# Call subscribers in the publishing process, as soon as a message is published
domain.config["message_processing"] = "sync"
# --8<-- [end:setup]

# --8<-- [start:subscribe]
pushed = []


@domain.subscriber(stream="user:notifications", broker="notifications")
class NotificationSubscriber:
    def __call__(self, payload: dict) -> None:
        # Send push notification to the user's device
        pushed.append((payload["user_id"], payload["title"]))


# --8<-- [end:subscribe]

# --8<-- [start:publish]
domain.init(traverse=False)

with domain.domain_context():
    # RPUSH the notification onto the "user:notifications" list
    domain.brokers["notifications"].publish(
        stream="user:notifications",
        message={
            "type": "notification",
            "user_id": "123",
            "title": "New Message",
            "body": "You have a new message!",
        },
    )
# --8<-- [end:publish]

# --8<-- [start:groups]
with domain.domain_context():
    broker = domain.brokers["notifications"]
    broker.publish("orders", {"type": "order.created", "order_id": "A1"})

    # Each group keeps its own position in the list, so both read the message
    _, billing_message = broker.get_next("orders", "billing")
    shipping_id, shipping_message = broker.get_next("orders", "shipping")

    # Acknowledgment is not supported: ack() returns False
    acknowledged = broker.ack("orders", shipping_id, "shipping")
# --8<-- [end:groups]


# --8<-- [start:health]
def health_check():
    broker = domain.brokers["notifications"]

    # Test connectivity
    if not broker.ping():
        return {"status": "unhealthy", "error": "Connection failed"}

    # Get health statistics; the Redis details sit under "details"
    stats = broker.health_stats()
    details = stats["details"]
    return {
        "status": stats["status"],
        "connected_clients": details["connected_clients"],
        "used_memory": details["used_memory_human"],
    }


with domain.domain_context():
    health = health_check()
# --8<-- [end:health]
# --8<-- [end:full]
