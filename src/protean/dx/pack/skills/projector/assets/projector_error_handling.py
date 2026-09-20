"""
Projector with error handling using handle_error classmethod.

This example demonstrates:
- Projector with a handle_error classmethod for custom error recovery
- The handle_error pattern for async event processing
- Standard projector structure with projection and aggregate
- Synchronous event processing for testing
- Error handling that logs failures without crashing the system

Usage:
    shipment = Shipment(tracking_id="TRACK-001", destination="NYC")
    shipment.dispatch()
    domain.repository_for(Shipment).add(shipment)
    # ShipmentProjector creates ShipmentStatus projection record
"""

import logging

from protean import Domain
from protean.core.projector import on
from protean.fields import Identifier, String

# Domain setup
domain = Domain()
domain.config["event_processing"] = "sync"

logger = logging.getLogger(__name__)


@domain.event(part_of="Shipment")
class ShipmentDispatched:
    """Event raised when a shipment is dispatched."""

    shipment_id: Identifier(required=True)
    tracking_id: String(required=True)
    destination: String(required=True)


@domain.aggregate
class Shipment:
    """Shipment aggregate tracking shipping lifecycle."""

    tracking_id: String(required=True)
    destination: String(required=True)
    status: String(default="pending")

    def dispatch(self):
        """Dispatch the shipment, raising ShipmentDispatched event."""
        if self.status == "dispatched":
            raise ValueError("Shipment already dispatched")
        self.status = "dispatched"
        self.raise_(
            ShipmentDispatched(
                shipment_id=self.id,
                tracking_id=self.tracking_id,
                destination=self.destination,
            )
        )


@domain.projection
class ShipmentStatus:
    """Projection tracking shipment status for querying.

    Provides a read-optimized view of shipment dispatch status.
    """

    shipment_id: Identifier(identifier=True, required=True)
    tracking_id: String(required=True)
    destination: String(required=True)
    status: String(default="dispatched")


@domain.projector(projector_for=ShipmentStatus, aggregates=[Shipment])
class ShipmentProjector:
    """Projector maintaining the ShipmentStatus projection.

    Includes handle_error classmethod for graceful error recovery
    during async event processing.
    """

    @on(ShipmentDispatched)
    def on_shipment_dispatched(self, event: ShipmentDispatched):
        """Create shipment status projection record."""
        repo = domain.repository_for(ShipmentStatus)
        status = ShipmentStatus(
            shipment_id=event.shipment_id,
            tracking_id=event.tracking_id,
            destination=event.destination,
            status="dispatched",
        )
        repo.add(status)

    @classmethod
    def handle_error(cls, exc: Exception, message) -> None:
        """Handle errors during async event processing.

        This method is called by the Protean engine when a projector
        method raises an exception during asynchronous processing.
        It is NOT called during synchronous processing.

        Args:
            exc: The exception that was raised
            message: The event message that caused the error
        """
        logger.error(
            f"ShipmentProjector failed to process event: {exc}, message: {message}"
        )


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Dispatch a shipment
        shipment = Shipment(tracking_id="TRACK-001", destination="New York")
        shipment.dispatch()
        domain.repository_for(Shipment).add(shipment)

        # Verify projection was created
        status = domain.repository_for(ShipmentStatus).get(shipment.id)
        print(f"Tracking: {status.tracking_id}, Destination: {status.destination}")
        print(f"Status: {status.status}")
        assert status.status == "dispatched"
        print("Error handling projector working correctly!")
