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
        event_type = payload.get("type")

        if event_type == "OrderPlaced":
            # Translate external payload into internal command
            current_domain.process(
                CreateShipment(
                    order_id=payload["order_id"],
                    customer_id=payload["customer_id"],
                    items=[
                        {"product_id": item["product_id"], "quantity": item["quantity"]}
                        for item in payload["items"]
                    ],
                    shipping_priority="standard",
                )
            )


# --8<-- [end:subscriber]
