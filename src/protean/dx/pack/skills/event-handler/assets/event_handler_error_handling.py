"""
Event handler with custom error handling via handle_error classmethod.

This example demonstrates:
- The optional handle_error classmethod for custom error recovery
- How the Protean engine calls handle_error when event processing fails
- Error logging and notification patterns
- The handle_error method signature: cls, exc, message

Note: The handle_error method is called by the Protean Engine during
asynchronous processing. In synchronous mode, exceptions propagate
directly to the caller. This example shows the handler structure
and how handle_error would be invoked by the engine.

Usage:
    shipment = Shipment(shipment_id="SHP-001", order_id="ORD-001", carrier="FedEx")
    shipment.dispatch()
    domain.repository_for(Shipment).add(shipment)
    # ShipmentNotifier processes ShipmentDispatched event
"""

import logging

from protean import Domain, handle
from protean.fields import Identifier, String, Text

# Domain setup
domain = Domain()
domain.config["event_processing"] = "sync"

logger = logging.getLogger(__name__)


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

    Uses the default auto-generated `id` field since log entries
    don't have a natural business identifier.
    """

    shipment_id: Identifier(required=True)
    message: Text(required=True)


@domain.event_handler(
    part_of=ShipmentLog, stream_category=Shipment.meta_.stream_category
)
class ShipmentNotifier:
    """Event handler for shipment events with custom error handling.

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
        """Handle ShipmentDispatched by creating a log entry."""
        log_entry = ShipmentLog(
            shipment_id=event.shipment_id,
            message=f"Shipment {event.shipment_id} dispatched via {event.carrier} "
            f"for order {event.order_id}",
        )
        domain.repository_for(ShipmentLog).add(log_entry)

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
        shipment.dispatch()
        domain.repository_for(Shipment).add(shipment)
        print("Shipment dispatched - notification logged")

        # Attempt to dispatch again (will fail)
        try:
            shipment.dispatch()
        except ValueError as e:
            print(f"Expected error: {e}")
            # In async mode, handle_error would be called by the engine
