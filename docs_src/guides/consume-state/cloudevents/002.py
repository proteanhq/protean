from protean import Domain, current_domain, handle
from protean.fields import Identifier, String
from protean.utils.eventing import Message

domain = Domain(name="Fulfilment")
domain.config["command_processing"] = "sync"


# --8<-- [start:subscriber]
@domain.aggregate
class ImportedOrder:
    external_id: Identifier(required=True)
    source: String(required=True)
    subject: String()


@domain.command(part_of=ImportedOrder)
class ImportOrder:
    external_id: Identifier(required=True)
    source: String(required=True)
    subject: String()


@domain.subscriber(stream="external-orders")
class ExternalOrderSubscriber:
    def __call__(self, payload: dict) -> None:
        message = Message.from_cloudevent(payload)

        # Access the event data
        order_id = message.data["order_id"]

        # Access CloudEvents-specific attributes
        source = message.metadata.extensions["ce_source"]
        subject = message.metadata.extensions.get("ce_subject")

        # Translate into a domain command
        current_domain.process(
            ImportOrder(external_id=order_id, source=source, subject=subject)
        )


# --8<-- [end:subscriber]


@domain.command_handler(part_of=ImportedOrder)
class ImportedOrderCommandHandler:
    @handle(ImportOrder)
    def import_order(self, command: ImportOrder) -> None:
        current_domain.repository_for(ImportedOrder).add(
            ImportedOrder(
                external_id=command.external_id,
                source=command.source,
                subject=command.subject,
            )
        )
