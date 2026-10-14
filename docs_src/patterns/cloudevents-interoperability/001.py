from protean import Domain


class KafkaProducer:
    """Stands in for a Kafka client and keeps what it was asked to send."""

    def __init__(self):
        self.sent = []

    def send(self, topic, value):
        self.sent.append((topic, value))


kafka_producer = KafkaProducer()

domain = Domain(name="Orders")
domain.config["event_processing"] = "sync"

# --8<-- [start:publisher]
import json

from protean import handle
from protean.fields import Auto, Float, Identifier
from protean.utils.eventing import Message


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    total: Float(required=True)

    def place(self):
        self.raise_(OrderPlaced(order_id=self.order_id, total=self.total))


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    total: Float(required=True)


@domain.event_handler(part_of=Order)
class OrderEventPublisher:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced) -> None:
        message = Message.from_domain_object(event)
        cloud_event = message.to_cloudevent()

        kafka_producer.send(
            topic="order-events",
            value=json.dumps(cloud_event).encode(),
        )


# --8<-- [end:publisher]
