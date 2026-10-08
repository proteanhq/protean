# --8<-- [start:imports]
import logging

from protean import Domain, handle
from protean.fields import Identifier, List, String
from protean.utils.globals import current_domain, g
from protean.utils.query import Q

logger = logging.getLogger(__name__)
# --8<-- [end:imports]

domain = Domain(name="Shipping", config={"command_processing": "sync"})


@domain.aggregate
class Shipment:
    order_id: Identifier(required=True)
    items: List(content_type=String)


@domain.aggregate
class ProcessedMessage:
    message_id: String(max_length=100, required=True)


@domain.command(part_of=Shipment)
class CreateShipment:
    order_id: Identifier(required=True)
    items: List(content_type=String)


@domain.command_handler(part_of=Shipment)
class ShipmentCommandHandler:
    @handle(CreateShipment)
    def create(self, command: CreateShipment) -> None:
        current_domain.repository_for(Shipment).add(
            Shipment(order_id=command.order_id, items=command.items)
        )


# --8<-- [start:subscriber]
@domain.subscriber(stream="orders")
class OrderSubscriber:
    def __call__(self, payload: dict) -> None:
        msg = g.message_in_context

        # Use the broker message ID for idempotency
        message_id = msg.metadata.headers.id
        repo = current_domain.repository_for(ProcessedMessage)
        if repo.exists(Q(message_id=message_id)):
            logger.info(f"Already processed {message_id}, skipping")
            return

        # Process the message
        current_domain.process(
            CreateShipment(order_id=payload["order_id"], items=payload["items"])
        )

        # Record that we processed this message
        repo.add(ProcessedMessage(message_id=message_id))


# --8<-- [end:subscriber]
