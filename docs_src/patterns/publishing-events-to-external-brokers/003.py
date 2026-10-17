from protean import Domain, handle
from protean.fields import Auto, Identifier, String
from protean.utils.globals import current_domain

# --8<-- [start:subscriber]
# In the Fulfillment domain
fulfillment = Domain(name="Fulfillment")


@fulfillment.subscriber(broker="default", stream="myapp::order")
class OrderEventSubscriber:
    def __call__(self, payload: dict) -> None:
        event_type = payload.get("metadata", {}).get("headers", {}).get("type", "")
        if event_type == "MyApp.OrderShipped.v1":
            data = payload.get("data", {})
            fulfillment.process(
                CreateShipment(
                    order_id=data["order_id"],
                    tracking_number=data["tracking_number"],
                )
            )


# --8<-- [end:subscriber]

fulfillment.config["command_processing"] = "sync"
fulfillment.config["message_processing"] = "sync"


@fulfillment.aggregate
class Shipment:
    shipment_id: Auto(identifier=True)
    order_id: Identifier(required=True)
    tracking_number: String(max_length=50)


@fulfillment.command(part_of=Shipment)
class CreateShipment:
    order_id: Identifier(required=True)
    tracking_number: String(max_length=50)


@fulfillment.command_handler(part_of=Shipment)
class ShipmentCommandHandler:
    @handle(CreateShipment)
    def create(self, command: CreateShipment):
        current_domain.repository_for(Shipment).add(Shipment(**command.payload))
