"""
Multiple events from one aggregate with multiple event handlers.

This example demonstrates:
- An aggregate raising different events from different methods
- Same-aggregate handler processing multiple event types
- A second handler in Shipment's cluster that hands off to Notification with
  a command
- Multiple handlers processing the same event independently
- Complete lifecycle: create → ship → deliver with events at each step

Scenario:
    A Shipment aggregate transitions through statuses (created → dispatched → delivered).
    Each transition raises a distinct event. A same-aggregate handler generates
    tracking updates. A second handler, also in Shipment's cluster, issues a
    SendNotification command, and Notification's command handler creates the alert.

Workflow:
    Shipment.dispatch() → ShipmentDispatched → ShipmentEventHandler (tracking)
                                              → ShipmentNotifier → SendNotification
    Shipment.deliver()  → ShipmentDelivered  → ShipmentEventHandler (tracking)
                                              → ShipmentNotifier → SendNotification

Events are delivered at least once, so each notification gets an id built from
the shipment id and the event type, and the command handler skips a
notification that already exists.
"""

from datetime import UTC

from protean import Domain, current_domain, handle
from protean.exceptions import ObjectNotFoundError
from protean.fields import DateTime, Identifier, String

# Domain setup
domain = Domain()

# Run each hop in-process: an event reaches its handlers when the unit of work
# that saves the shipment commits, and SendNotification reaches its handler as
# soon as it is issued.
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


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

    Events are delivered at least once, so a repeat of ShipmentDispatched can
    arrive after the shipment was delivered. `on_dispatched` writes only while
    the shipment is still dispatched, so that repeat cannot reset the tracking
    info. `on_delivered` returns when the delivered tracking info is already
    set, so a repeat does not save the shipment again.
    """

    @handle(ShipmentDispatched)
    def on_dispatched(self, event: ShipmentDispatched):
        """Generate tracking info when shipment is dispatched."""
        repo = domain.repository_for(Shipment)
        shipment = repo.get(event.shipment_id)
        if shipment.status != "dispatched":
            return  # a late repeat; the shipment has moved on
        shipment.tracking_info = f"TRACK-{event.carrier}-{event.shipment_id}"
        repo.add(shipment)

    @handle(ShipmentDelivered)
    def on_delivered(self, event: ShipmentDelivered):
        """Update tracking info when shipment is delivered."""
        repo = domain.repository_for(Shipment)
        shipment = repo.get(event.shipment_id)
        tracking_info = f"DELIVERED-{event.shipment_id}"
        if shipment.tracking_info == tracking_info:
            return  # already applied
        shipment.tracking_info = tracking_info
        repo.add(shipment)


# --- Notification (the aggregate that receives the alerts) ---


@domain.aggregate
class Notification:
    """Notification aggregate for user-facing alerts."""

    notification_id: Identifier(identifier=True)
    recipient: String(required=True)
    message: String(required=True)
    notification_type: String(required=True)


@domain.command(part_of="Notification")
class SendNotification:
    """Send one alert about a shipment.

    `notification_id` is built from the event, so a redelivered event reissues
    the same command and the handler can tell the alert already exists.
    """

    notification_id: Identifier(required=True)
    recipient: String(required=True)
    message: String(required=True)
    notification_type: String(required=True)


@domain.command_handler(part_of=Notification)
class NotificationCommandHandler:
    """The write path for Notification."""

    @handle(SendNotification)
    def send_notification(self, command: SendNotification):
        repo = current_domain.repository_for(Notification)
        try:
            repo.get(command.notification_id)
        except ObjectNotFoundError:
            repo.add(
                Notification(
                    notification_id=command.notification_id,
                    recipient=command.recipient,
                    message=command.message,
                    notification_type=command.notification_type,
                )
            )
        else:
            return  # already sent; a redelivered event must not alert twice


# --- Second Shipment handler (hands off to Notification) ---


@domain.event_handler(part_of=Shipment)
class ShipmentNotifier:
    """Send an alert for each shipment event.

    The handler sits in Shipment's cluster, because it reacts to Shipment's own
    events (a handler that reacts to another cluster's event is what `check`
    reports as EVENT_HANDLER_FOREIGN_EVENT). It hands off to Notification with
    a command. It also shows two handlers processing the same events
    independently.
    """

    @handle(ShipmentDispatched)
    def on_dispatched(self, event: ShipmentDispatched):
        """Ask Notification to send a dispatch alert."""
        current_domain.process(
            SendNotification(
                notification_id=f"{event.shipment_id}:dispatch",
                recipient=event.order_id,
                message=f"Shipment {event.shipment_id} dispatched via {event.carrier}",
                notification_type="dispatch",
            )
        )

    @handle(ShipmentDelivered)
    def on_delivered(self, event: ShipmentDelivered):
        """Ask Notification to send a delivery alert."""
        current_domain.process(
            SendNotification(
                notification_id=f"{event.shipment_id}:delivery",
                recipient=event.order_id,
                message=f"Shipment {event.shipment_id} delivered",
                notification_type="delivery",
            )
        )


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
