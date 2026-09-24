"""
Subscriber with event routing: Multiple external event types.

This example demonstrates:
- A subscriber handling multiple external event types from one stream
- Routing logic based on event type field
- Different translation strategies for each event type
- Creating different aggregates from different event types
- Logging for unrecognized event types

Domain: A shipping integration where an external logistics provider
sends tracking events (picked up, in transit, delivered) via a
broker stream. Each event type triggers different domain updates.
"""

import logging

from protean import Domain
from protean.fields import DateTime, Identifier, String

domain = Domain(__name__)
domain.config["message_processing"] = "sync"

logger = logging.getLogger(__name__)


# --- Aggregates ---


@domain.aggregate
class Shipment:
    """Shipment aggregate tracking package delivery."""

    shipment_id: Identifier(identifier=True)
    order_id: Identifier(required=True)
    carrier: String(max_length=100)
    tracking_number: String(max_length=100)
    status: String(default="pending")
    last_location: String(max_length=200)
    delivered_at: DateTime()

    def mark_picked_up(self, carrier, tracking_number):
        """Mark shipment as picked up by carrier."""
        self.carrier = carrier
        self.tracking_number = tracking_number
        self.status = "in_transit"

    def update_location(self, location):
        """Update current location during transit."""
        self.last_location = location

    def mark_delivered(self, delivered_at):
        """Mark shipment as delivered."""
        self.status = "delivered"
        self.delivered_at = delivered_at


# --- Subscriber ---


@domain.subscriber(stream="logistics_tracking")
class LogisticsTrackingSubscriber:
    """Processes tracking events from external logistics provider.

    Routes different event types to appropriate handler methods.
    Each external event type maps to a different shipment operation.

    External events:
    - pickup: {"event": "pickup", "shipmentId": "...", "carrier": "...", "trackingNo": "..."}
    - location_update: {"event": "location_update", "shipmentId": "...", "currentLocation": "..."}
    - delivery: {"event": "delivery", "shipmentId": "...", "deliveredAt": "..."}
    """

    def __call__(self, payload: dict) -> None:
        """Route external tracking events."""
        event = payload.get("event", "")

        if event == "pickup":
            self._handle_pickup(payload)
        elif event == "location_update":
            self._handle_location_update(payload)
        elif event == "delivery":
            self._handle_delivery(payload)
        else:
            logger.warning("Unknown logistics event: %s", event)

    def _handle_pickup(self, payload: dict) -> None:
        """Handle pickup event: mark shipment as in transit."""
        repo = domain.repository_for(Shipment)
        shipment = repo.get(payload["shipmentId"])
        shipment.mark_picked_up(
            carrier=payload["carrier"],
            tracking_number=payload["trackingNo"],
        )
        repo.add(shipment)

    def _handle_location_update(self, payload: dict) -> None:
        """Handle location update: update last known location."""
        repo = domain.repository_for(Shipment)
        shipment = repo.get(payload["shipmentId"])
        shipment.update_location(location=payload["currentLocation"])
        repo.add(shipment)

    def _handle_delivery(self, payload: dict) -> None:
        """Handle delivery event: mark shipment as delivered."""
        repo = domain.repository_for(Shipment)
        shipment = repo.get(payload["shipmentId"])
        shipment.mark_delivered(delivered_at=payload["deliveredAt"])
        repo.add(shipment)
