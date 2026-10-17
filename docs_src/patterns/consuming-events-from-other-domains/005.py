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


@domain.aggregate
class CustomerProfile:
    customer_id: Identifier(identifier=True)
    default_shipping_address: String()
    shipping_tier: String(default="standard")


# --8<-- [start:subscriber]
@domain.subscriber(stream="orders")
class OrderEventsSubscriber:
    def __call__(self, payload: dict) -> None:
        if payload.get("type") != "OrderPlaced":
            return

        # Enrich with data from our domain
        customer_repo = current_domain.repository_for(CustomerProfile)
        customer = customer_repo.get(payload["customer_id"])

        current_domain.process(
            CreateShipment(
                order_id=payload["order_id"],
                customer_id=payload["customer_id"],
                shipping_address=customer.default_shipping_address,
                shipping_priority=customer.shipping_tier,
                items=payload["items"],
            )
        )


# --8<-- [end:subscriber]
