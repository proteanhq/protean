# --8<-- [start:full]
from protean import Domain
from protean.port.broker import BrokerCapabilities

domain = Domain(name="Capabilities")
domain.init(traverse=False)

with domain.domain_context():
    # Get a broker instance
    broker = domain.brokers["default"]
    broker.publish("orders", {"order_id": "A1"})

    # Check for one capability
    if BrokerCapabilities.CONSUMER_GROUPS in broker.capabilities:
        # Read up to 10 messages as the "order-processor" group
        messages = broker.read(
            stream="orders",
            consumer_group="order-processor",
            limit=10,
        )

    # Check for all of several capabilities
    required = BrokerCapabilities.CONSUMER_GROUPS | BrokerCapabilities.ACK_NACK
    if (broker.capabilities & required) == required:
        # Acknowledge each message once it is handled
        for identifier, _message in messages:
            broker.ack("orders", identifier, "order-processor")
# --8<-- [end:full]
