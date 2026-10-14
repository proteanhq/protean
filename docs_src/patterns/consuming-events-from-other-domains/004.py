from protean import Domain, handle
from protean.fields import Auto, Identifier, List, String
from protean.utils.globals import current_domain

domain = Domain(name="Fulfillment")
domain.config["command_processing"] = "sync"
domain.config["message_processing"] = "sync"


@domain.aggregate
class Shipment:
    shipment_id: Auto(identifier=True)
    order_id: Identifier(required=True)
    customer_id: Identifier()
    items: List()
    shipping_priority: String(default="standard")
    shipping_address: String()


@domain.command(part_of=Shipment)
class CreateShipment:
    order_id: Identifier(required=True)
    customer_id: Identifier()
    items: List()
    shipping_priority: String(default="standard")
    shipping_address: String()


@domain.command_handler(part_of=Shipment)
class ShipmentCommandHandler:
    @handle(CreateShipment)
    def create(self, command: CreateShipment):
        current_domain.repository_for(Shipment).add(Shipment(**command.payload))


# --8<-- [start:subscriber]
@domain.subscriber(stream="orders")
class OrderEventsSubscriber:
    def __call__(self, payload: dict) -> None:
        if payload.get("type") != "OrderPlaced":
            return  # Ignore event types we don't care about

        # Only create shipments for physical items
        physical_items = [
            item for item in payload["items"] if item.get("type") != "digital"
        ]

        if not physical_items:
            return  # Nothing for Fulfillment to do

        current_domain.process(
            CreateShipment(
                order_id=payload["order_id"],
                customer_id=payload["customer_id"],
                items=physical_items,
            )
        )


# --8<-- [end:subscriber]
