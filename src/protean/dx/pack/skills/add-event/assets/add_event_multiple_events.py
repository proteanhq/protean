"""
Multiple events from one aggregate with multiple event handlers.

This example demonstrates:
- An aggregate raising different events from different methods
- Same-aggregate handler processing multiple event types
- Cross-aggregate handler reacting to selected events
- Multiple handlers processing the same event independently
- Complete lifecycle: create → ship → deliver with events at each step

Scenario:
    A Shipment aggregate transitions through statuses (created → dispatched → delivered).
    Each transition raises a distinct event. A same-aggregate handler generates
    tracking updates, while a cross-aggregate Notification handler sends alerts.

Workflow:
    Shipment.dispatch() → ShipmentDispatched → ShipmentEventHandler (tracking)
                                              → NotificationHandler (alert)
    Shipment.deliver()  → ShipmentDelivered  → ShipmentEventHandler (tracking)
                                              → NotificationHandler (alert)
"""

from datetime import UTC

from protean import Domain, handle
from protean.fields import DateTime, Identifier, String

# Domain setup
domain = Domain()
domain.config["event_processing"] = "sync"


# --- Events ---


@domain.event(part_of="Shipment")
class ShipmentDispatched:
    """Event raised when a shipment is dispatched for delivery."""

    shipment_id: Identifier(required=True)
    order_id: Identifier(required=True)
    carrier: String(required=True)


@domain.event(part_of="Shipment")
class ShipmentDelivered:
    """Event raised when a shipment is successfully delivered."""

    shipment_id: Identifier(required=True)
    order_id: Identifier(required=True)
    delivered_at: DateTime(required=True)


# --- Source Aggregate ---


@domain.aggregate
class Shipment:
    """Shipment aggregate tracking package delivery lifecycle."""

    shipment_id: Identifier(identifier=True)
    order_id: Identifier(required=True)
    carrier: String(required=True)
    status: String(default="created")
    tracking_info: String()
    delivered_at: DateTime()

    def dispatch(self):
        """Dispatch the shipment for delivery."""
        if self.status != "created":
            raise ValueError(f"Cannot dispatch shipment in '{self.status}' status")
        self.status = "dispatched"

        self.raise_(
            ShipmentDispatched(
                shipment_id=self.shipment_id,
                order_id=self.order_id,
                carrier=self.carrier,
            )
        )

    def deliver(self, delivered_at):
        """Mark shipment as delivered."""
        if self.status != "dispatched":
            raise ValueError(f"Cannot deliver shipment in '{self.status}' status")
        self.status = "delivered"
        self.delivered_at = delivered_at

        self.raise_(
            ShipmentDelivered(
                shipment_id=self.shipment_id,
                order_id=self.order_id,
                delivered_at=delivered_at,
            )
        )


# --- Same-aggregate Event Handler ---


@domain.event_handler(part_of=Shipment)
class ShipmentEventHandler:
    """Handler for Shipment's own events.

    Processes multiple event types from the same aggregate.
    Generates tracking info updates as the shipment progresses.
    """

    @handle(ShipmentDispatched)
    def on_dispatched(self, event: ShipmentDispatched):
        """Generate tracking info when shipment is dispatched."""
        repo = domain.repository_for(Shipment)
        shipment = repo.get(event.shipment_id)
        shipment.tracking_info = f"TRACK-{event.carrier}-{event.shipment_id}"
        repo.add(shipment)

    @handle(ShipmentDelivered)
    def on_delivered(self, event: ShipmentDelivered):
        """Update tracking info when shipment is delivered."""
        repo = domain.repository_for(Shipment)
        shipment = repo.get(event.shipment_id)
        shipment.tracking_info = f"DELIVERED-{event.shipment_id}"
        repo.add(shipment)


# --- Cross-aggregate Event Handler (Notification) ---


@domain.aggregate
class Notification:
    """Notification aggregate for user-facing alerts."""

    recipient: String(required=True)
    message: String(required=True)
    notification_type: String(required=True)


@domain.event_handler(
    part_of=Notification, stream_category=Shipment.meta_.stream_category
)
class NotificationHandler:
    """Cross-aggregate handler that sends notifications for shipment events.

    Belongs to Notification aggregate but listens to Shipment's stream.
    Demonstrates multiple handlers processing the same events independently.
    """

    @handle(ShipmentDispatched)
    def on_dispatched(self, event: ShipmentDispatched):
        """Send dispatch notification."""
        notification = Notification(
            recipient=event.order_id,
            message=f"Shipment {event.shipment_id} dispatched via {event.carrier}",
            notification_type="dispatch",
        )
        domain.repository_for(Notification).add(notification)

    @handle(ShipmentDelivered)
    def on_delivered(self, event: ShipmentDelivered):
        """Send delivery notification."""
        notification = Notification(
            recipient=event.order_id,
            message=f"Shipment {event.shipment_id} delivered",
            notification_type="delivery",
        )
        domain.repository_for(Notification).add(notification)


# Example usage
if __name__ == "__main__":  # pragma: no cover
    from datetime import datetime

    domain.init(traverse=False)

    with domain.domain_context():
        # Create and dispatch a shipment
        shipment = Shipment(
            shipment_id="SHIP-001",
            order_id="ORD-001",
            carrier="FedEx",
        )
        shipment.dispatch()
        domain.repository_for(Shipment).add(shipment)

        # Check tracking was generated
        updated = domain.repository_for(Shipment).get("SHIP-001")
        print(f"After dispatch: {updated.tracking_info}")

        # Deliver the shipment
        now = datetime.now(UTC)
        updated.deliver(delivered_at=now)
        domain.repository_for(Shipment).add(updated)

        # Check final tracking
        final = domain.repository_for(Shipment).get("SHIP-001")
        print(f"After delivery: {final.tracking_info}")
