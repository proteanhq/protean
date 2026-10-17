from protean import Domain, handle
from protean.fields import Auto, Identifier, List
from protean.utils.globals import current_domain

# --8<-- [start:subscriber]
# In the Fulfillment domain: subscriber consumes the event
domain = Domain(name="Fulfillment")


@domain.subscriber(stream="orders")
class OrderEventsSubscriber:
    def __call__(self, payload: dict):
        # The subscriber can act entirely from the event data
        # No need to call back to the Order domain
        # Protean publishes the event fields under "data", beside "metadata"
        data = payload["data"]
        current_domain.process(
            CreateShipment(
                order_id=data["order_id"],
                customer_id=data["customer_id"],
                items=data["items"],
            )
        )


# --8<-- [end:subscriber]

domain.config["command_processing"] = "sync"
domain.config["message_processing"] = "sync"


@domain.aggregate
class Shipment:
    shipment_id: Auto(identifier=True)
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List()


@domain.command(part_of=Shipment)
class CreateShipment:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List()


@domain.command_handler(part_of=Shipment)
class ShipmentCommandHandler:
    @handle(CreateShipment)
    def create(self, command: CreateShipment):
        current_domain.repository_for(Shipment).add(
            Shipment(
                order_id=command.order_id,
                customer_id=command.customer_id,
                items=command.items,
            )
        )
