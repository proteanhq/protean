# --8<-- [start:full]
from protean import Domain
from protean.port.broker import BrokerCapabilities

domain = Domain(name="Capabilities")
domain.init(traverse=False)

with domain.domain_context():
    # Get a broker instance
    broker = domain.brokers["default"]
    broker.publish("orders", {"order_id": "A1"})

    # Check for specific capabilities
    if broker.has_capability(BrokerCapabilities.CONSUMER_GROUPS):
        # Read up to 10 messages as the "order-processor" group
        messages = broker.read(
            stream="orders",
            consumer_group="order-processor",
            no_of_messages=10,
        )

    # Check for any of multiple capabilities
    if broker.has_any_capability(
        BrokerCapabilities.ACK_NACK | BrokerCapabilities.DEAD_LETTER_QUEUE
    ):
        # Acknowledge each message once it is handled
        for identifier, _message in messages:
            broker.ack("orders", identifier, "order-processor")
# --8<-- [end:full]
