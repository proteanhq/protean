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


# --8<-- [start:both_versions]
def __call__(self, payload: dict) -> None:
    # Handle both v1 and v2 field names
    items = payload.get("line_items") or payload.get("items", [])

    current_domain.process(
        CreateShipment(
            order_id=payload["order_id"],
            items=items,
        )
    )


# --8<-- [end:both_versions]


@domain.subscriber(stream="orders")
class OrderEventsSubscriber:
    __call__ = __call__
