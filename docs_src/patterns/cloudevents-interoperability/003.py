from protean import Domain, handle
from protean.fields import Auto, Float, Identifier
from protean.utils.globals import current_domain

domain = Domain(name="Orders")
domain.config["command_processing"] = "sync"
domain.config["event_processing"] = "sync"


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


@domain.command(part_of=Order)
class PlaceOrder:
    total: Float(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place(self, command: PlaceOrder):
        order = Order(total=command.total)
        order.place()
        current_domain.repository_for(Order).add(order)


# --8<-- [start:round_trip]
from protean.utils.eventing import Message


def publish(broker, event):
    """Service A: publish the event as a CloudEvent."""
    message = Message.from_domain_object(event)
    broker.publish("shared-topic", message.to_cloudevent())


def consume(broker):
    """Service B: consume the CloudEvent and rebuild the event."""
    _, cloud_event = broker.get_next("shared-topic", "fulfillment")
    message = Message.from_cloudevent(cloud_event)
    return message.to_domain_object()  # Works if the type is registered


# --8<-- [end:round_trip]


@domain.event_handler(part_of=Order)
class SharedTopicPublisher:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced) -> None:
        publish(current_domain.brokers["default"], event)
