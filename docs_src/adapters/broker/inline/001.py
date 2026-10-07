# --8<-- [start:full]
# --8<-- [start:basic]
from protean import Domain

domain = Domain(name="Users")
domain.config["brokers"] = {"default": {"provider": "inline"}}

# Call subscribers in the publishing process, as soon as a message is published
domain.config["message_processing"] = "sync"

created = []


# Subscribing to messages
@domain.subscriber(stream="user-events")
class UserEventSubscriber:
    def __call__(self, payload: dict) -> None:
        if payload["type"] == "user.created":
            print(f"User created: {payload['name']}")
            created.append(payload["user_id"])


# Register subscribers before initializing the domain
domain.init(traverse=False)

with domain.domain_context():
    # Publishing messages
    domain.brokers.publish(
        stream="user-events",
        message={"type": "user.created", "user_id": "123", "name": "John Doe"},
    )
# --8<-- [end:basic]

# --8<-- [start:consumer_groups]
with domain.domain_context():
    broker = domain.brokers["default"]
    broker.publish("orders", {"type": "order.created", "order_id": "A1"})

    # Each consumer group receives every message on the stream
    billing_id, billing_message = broker.get_next("orders", "billing")
    shipping_id, shipping_message = broker.get_next("orders", "shipping")

    # Within one group, each message is handed out once. Acknowledge it when done.
    broker.ack("orders", billing_id, "billing")
    broker.ack("orders", shipping_id, "shipping")
# --8<-- [end:consumer_groups]
# --8<-- [end:full]
