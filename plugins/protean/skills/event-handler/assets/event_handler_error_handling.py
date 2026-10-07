"""
Event handler with custom error handling via handle_error classmethod.

This example demonstrates:
- The optional handle_error classmethod for custom error recovery
- How the Protean engine calls handle_error when event processing fails
- Error logging and notification patterns
- The handle_error method signature: cls, exc, message
- The handler sits in Shipment's cluster (part_of=Shipment), the cluster that
  owns ShipmentDispatched, and writes the log entry through a command to
  ShipmentLog
- A redelivered event is a no-op: events are delivered at least once, so the
  command carries a log id built from the shipment id, and ShipmentLog's
  command handler skips an entry that already exists

Note: The handle_error method is called by the Protean Engine during
asynchronous processing. In synchronous mode, exceptions propagate
directly to the caller. This example shows the handler structure
and how handle_error would be invoked by the engine.

Usage:
    shipment = Shipment(shipment_id="SHP-001", order_id="ORD-001", carrier="FedEx")
    domain.repository_for(Shipment).add(shipment)
    domain.process(DispatchShipment(shipment_id="SHP-001"))
    # ShipmentNotifier processes ShipmentDispatched and issues RecordShipmentLog
"""

import logging

from protean import Domain, current_domain, handle
from protean.exceptions import ObjectNotFoundError
from protean.fields import Identifier, String, Text

# Domain setup
domain = Domain()
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"

logger = logging.getLogger(__name__)


@domain.command(part_of="Shipment")
class DispatchShipment:
    """Command to dispatch a shipment."""

    shipment_id: Identifier(required=True)


@domain.command(part_of="ShipmentLog")
class RecordShipmentLog:
    """Command to record one log entry for a shipment.

    `log_id` is built from the event, so a redelivered event reissues the same
    command and the handler can tell the entry already exists.
    """

    log_id: Identifier(required=True)
    shipment_id: Identifier(required=True)
    message: Text(required=True)


@domain.event(part_of="Shipment")
class ShipmentDispatched:
    """Event raised when a shipment is dispatched."""

    shipment_id: Identifier(required=True)
    order_id: Identifier(required=True)
    carrier: String(required=True)


@domain.aggregate
class Shipment:
    """Shipment aggregate tracking delivery of orders."""

    shipment_id: Identifier(identifier=True)
    order_id: Identifier(required=True)
    carrier: String(required=True)
    status: String(default="pending")

    def dispatch(self):
        """Dispatch the shipment, raising ShipmentDispatched event."""
        if self.status != "pending":
            raise ValueError(f"Cannot dispatch shipment in '{self.status}' status")
        self.status = "dispatched"
        self.raise_(
            ShipmentDispatched(
                shipment_id=self.shipment_id,
                order_id=self.order_id,
                carrier=self.carrier,
            )
        )


@domain.aggregate
class ShipmentLog:
    """Aggregate for tracking shipment notification logs.

    `log_id` is set by the caller from the event that caused the entry, so one
    event produces at most one entry.
    """

    log_id: Identifier(identifier=True)
    shipment_id: Identifier(required=True)
    message: Text(required=True)


@domain.command_handler(part_of=Shipment)
class ShipmentCommandHandler:
    """The write path for Shipment."""

    @handle(DispatchShipment)
    def dispatch_shipment(self, command: DispatchShipment):
        repo = current_domain.repository_for(Shipment)
        shipment = repo.get(command.shipment_id)
        shipment.dispatch()
        repo.add(shipment)


@domain.command_handler(part_of=ShipmentLog)
class ShipmentLogCommandHandler:
    """The write path for ShipmentLog."""

    @handle(RecordShipmentLog)
    def record_shipment_log(self, command: RecordShipmentLog):
        repo = current_domain.repository_for(ShipmentLog)
        try:
            repo.get(command.log_id)
        except ObjectNotFoundError:
            repo.add(
                ShipmentLog(
                    log_id=command.log_id,
                    shipment_id=command.shipment_id,
                    message=command.message,
                )
            )
        else:
            return  # already recorded; a second entry would repeat the log


@domain.event_handler(part_of=Shipment)
class ShipmentNotifier:
    """Event handler for shipment events with custom error handling.

    It sits in Shipment's cluster because ShipmentDispatched belongs to
    Shipment, and it writes to ShipmentLog only through a command.

    The handle_error classmethod is called by the Protean Engine when
    an exception occurs during asynchronous event processing. It provides
    a hook for logging, notification, or recovery logic.

    Error handling flow:
    1. Handler method raises exception
    2. Engine catches the exception and logs it
    3. Engine calls handle_error(exc, message)
    4. Processing continues with the next event
    """

    @handle(ShipmentDispatched)
    def on_shipment_dispatched(self, event: ShipmentDispatched):
        """Handle ShipmentDispatched by asking ShipmentLog for a log entry."""
        current_domain.process(
            RecordShipmentLog(
                # A shipment is dispatched once, so this id names one entry.
                log_id=f"{event.shipment_id}:dispatched",
                shipment_id=event.shipment_id,
                message=f"Shipment {event.shipment_id} dispatched via "
                f"{event.carrier} for order {event.order_id}",
            )
        )

    @classmethod
    def handle_error(cls, exc: Exception, message) -> None:
        """Custom error handling for failed shipment event processing.

        Called by the Protean Engine when an exception occurs during
        asynchronous event processing. The default implementation
        in HandlerMixin does nothing; override to add custom behavior.

        Args:
            exc: The exception that was raised during handling
            message: The original event message being processed
        """
        logger.error(
            "Shipment event processing failed: %s (type: %s)",
            str(exc),
            type(exc).__name__,
        )


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create and dispatch a shipment
        shipment = Shipment(
            shipment_id="SHP-001",
            order_id="ORD-001",
            carrier="FedEx",
        )
        domain.repository_for(Shipment).add(shipment)
        domain.process(DispatchShipment(shipment_id="SHP-001"))
        log = domain.repository_for(ShipmentLog).get("SHP-001:dispatched")
        print(f"Shipment dispatched - logged: {log.message}")

        # Attempt to dispatch again (will fail)
        try:
            domain.process(DispatchShipment(shipment_id="SHP-001"))
        except ValueError as e:
            # The command handler raised this, before any event was raised,
            # so ShipmentNotifier.handle_error is not involved. The engine
            # calls handle_error only when ShipmentNotifier's own method fails
            # while the server processes events asynchronously.
            print(f"Expected error: {e}")
