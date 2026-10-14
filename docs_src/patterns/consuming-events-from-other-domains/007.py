import logging

from protean import Domain, handle
from protean.exceptions import ValidationError
from protean.fields import Auto, Identifier, List, String
from protean.utils.globals import current_domain

logger = logging.getLogger(__name__)

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
    customer_id: Identifier(required=True)
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
        # Validate the external data before trusting it
        if not payload.get("order_id"):
            logger.warning("Received OrderPlaced without order_id, skipping")
            return

        if not payload.get("items"):
            logger.warning(
                f"Received OrderPlaced with no items for {payload['order_id']}"
            )
            return

        try:
            current_domain.process(
                CreateShipment(
                    order_id=payload["order_id"],
                    customer_id=payload.get("customer_id"),
                    items=payload["items"],
                )
            )
        except ValidationError as e:
            logger.error(f"Failed to process OrderPlaced {payload['order_id']}: {e}")
            # Don't re-raise -- the external event was received,
            # the error is in our translation or domain rules.
            # Log for investigation rather than blocking the subscription.


# --8<-- [end:subscriber]
