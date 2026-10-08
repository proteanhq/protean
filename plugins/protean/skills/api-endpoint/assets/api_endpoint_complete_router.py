"""
Complete FastAPI app: one router for one aggregate, and the app factory.

This example demonstrates:
- A ``create_app(domain)`` factory built on ``protean.integrations.fastapi``:
  ``DomainContextMiddleware`` pushes the domain context for each request, and
  ``register_exception_handlers`` turns Protean exceptions into HTTP responses
- An ``APIRouter`` with several endpoints for the same aggregate (create,
  update tracking, deliver, cancel)
- Plain ``def`` endpoints. FastAPI runs them in its thread pool, so the
  synchronous ``domain.process(..., asynchronous=False)`` call does not block
  the event loop
- Pydantic request models that check types only, while the command's fields
  and the aggregate enforce the domain rules

The other api-endpoint assets show routers only. Mount any of them with this
same factory.

Status codes this app returns:
- 201 / 200 on success
- 400 when the command's fields reject the input (``ValidationError``), with
  ``{"error": {"<field>": ["<message>", ...]}}``
- 404 when the shipment does not exist (``ObjectNotFoundError``)
- 409 when the shipment is in the wrong state (``InvalidStateError``)
- 422 from FastAPI itself when the body does not match the Pydantic model

Usage:
    # Start the server (needs: pip install "protean[server]")
    python api_endpoint_complete_router.py

    # Create a shipment
    curl -X POST http://localhost:8000/shipments \\
        -H "Content-Type: application/json" \\
        -d '{"shipment_id": "SHP-001", "origin": "NYC", "destination": "LAX", "weight": 25.5}'

    # Update tracking
    curl -X PUT http://localhost:8000/shipments/SHP-001/tracking \\
        -H "Content-Type: application/json" \\
        -d '{"tracking_number": "TRACK-12345", "carrier": "FedEx"}'

    # Mark as delivered
    curl -X PUT http://localhost:8000/shipments/SHP-001/deliver

    # Cancel shipment (409, because it is already delivered)
    curl -X PUT http://localhost:8000/shipments/SHP-001/cancel \\
        -H "Content-Type: application/json" \\
        -d '{"reason": "Customer changed address"}'
"""

from datetime import UTC, datetime

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

from protean import Domain, handle
from protean.exceptions import InvalidStateError
from protean.fields import DateTime, Float, Identifier, String
from protean.integrations.fastapi import (
    DomainContextMiddleware,
    register_exception_handlers,
)
from protean.utils.globals import current_domain

domain = Domain()


@domain.aggregate
class Shipment:
    """Shipment aggregate with full lifecycle operations."""

    shipment_id: Identifier(identifier=True)
    origin: String(required=True, max_length=50)
    destination: String(required=True, max_length=50)
    weight: Float(required=True, min_value=0.1)
    status: String(default="created")
    tracking_number: String()
    carrier: String()
    created_at: DateTime()
    delivered_at: DateTime()
    cancelled_at: DateTime()
    cancel_reason: String()

    def create(self):
        """Mark shipment as created."""
        self.status = "created"
        self.created_at = datetime.now(UTC)

    def update_tracking(self, tracking_number: str, carrier: str):
        """Update tracking information."""
        if self.status not in ("created", "in_transit"):
            raise InvalidStateError(
                f"Cannot update tracking for '{self.status}' shipment"
            )
        self.tracking_number = tracking_number
        self.carrier = carrier
        self.status = "in_transit"

    def deliver(self):
        """Mark shipment as delivered."""
        if self.status != "in_transit":
            raise InvalidStateError(
                f"Cannot deliver shipment in '{self.status}' status"
            )
        self.status = "delivered"
        self.delivered_at = datetime.now(UTC)

    def cancel(self, reason: str):
        """Cancel the shipment."""
        if self.status in ("delivered", "cancelled"):
            raise InvalidStateError(f"Cannot cancel shipment in '{self.status}' status")
        self.status = "cancelled"
        self.cancelled_at = datetime.now(UTC)
        self.cancel_reason = reason


# --- Commands ---


@domain.command(part_of="Shipment")
class CreateShipment:
    """Command to create a new shipment."""

    shipment_id: Identifier(required=True)
    origin: String(required=True, max_length=50)
    destination: String(required=True, max_length=50)
    weight: Float(required=True, min_value=0.1)


@domain.command(part_of="Shipment")
class UpdateTracking:
    """Command to update tracking information."""

    shipment_id: Identifier(required=True)
    tracking_number: String(required=True)
    carrier: String(required=True)


@domain.command(part_of="Shipment")
class DeliverShipment:
    """Command to mark shipment as delivered."""

    shipment_id: Identifier(required=True)


@domain.command(part_of="Shipment")
class CancelShipment:
    """Command to cancel a shipment."""

    shipment_id: Identifier(required=True)
    reason: String(required=True)


# --- Command Handler ---


@domain.command_handler(part_of=Shipment)
class ShipmentCommandHandler:
    """Handler for all shipment commands."""

    @handle(CreateShipment)
    def handle_create(self, command: CreateShipment):
        """Create a new shipment."""
        shipment = Shipment(
            shipment_id=command.shipment_id,
            origin=command.origin,
            destination=command.destination,
            weight=command.weight,
        )
        shipment.create()
        current_domain.repository_for(Shipment).add(shipment)
        return shipment.shipment_id

    @handle(UpdateTracking)
    def handle_update_tracking(self, command: UpdateTracking):
        """Update tracking on an existing shipment."""
        # ``get`` raises ObjectNotFoundError for an unknown id, which the
        # registered exception handlers turn into a 404.
        shipment = current_domain.repository_for(Shipment).get(command.shipment_id)
        shipment.update_tracking(
            tracking_number=command.tracking_number,
            carrier=command.carrier,
        )
        current_domain.repository_for(Shipment).add(shipment)
        return shipment.shipment_id

    @handle(DeliverShipment)
    def handle_deliver(self, command: DeliverShipment):
        """Mark a shipment as delivered."""
        shipment = current_domain.repository_for(Shipment).get(command.shipment_id)
        shipment.deliver()
        current_domain.repository_for(Shipment).add(shipment)
        return shipment.shipment_id

    @handle(CancelShipment)
    def handle_cancel(self, command: CancelShipment):
        """Cancel a shipment."""
        shipment = current_domain.repository_for(Shipment).get(command.shipment_id)
        shipment.cancel(reason=command.reason)
        current_domain.repository_for(Shipment).add(shipment)
        return shipment.shipment_id


# --- Request models: types only, no domain rules ---


class CreateShipmentRequest(BaseModel):
    shipment_id: str
    origin: str
    destination: str
    weight: float


class UpdateTrackingRequest(BaseModel):
    tracking_number: str
    carrier: str


class CancelShipmentRequest(BaseModel):
    reason: str


# --- Router ---

router = APIRouter(prefix="/shipments", tags=["shipments"])


@router.post("", status_code=201)
def create_shipment(body: CreateShipmentRequest):
    """Create a new shipment."""
    command = CreateShipment(
        shipment_id=body.shipment_id,
        origin=body.origin,
        destination=body.destination,
        weight=body.weight,
    )
    result = current_domain.process(command, asynchronous=False)
    return {"shipment_id": result, "status": "created"}


@router.put("/{shipment_id}/tracking")
def update_tracking(shipment_id: str, body: UpdateTrackingRequest):
    """Update tracking. The path names the shipment; the body has the data."""
    command = UpdateTracking(
        shipment_id=shipment_id,
        tracking_number=body.tracking_number,
        carrier=body.carrier,
    )
    result = current_domain.process(command, asynchronous=False)
    return {"shipment_id": result, "status": "in_transit"}


@router.put("/{shipment_id}/deliver")
def deliver_shipment(shipment_id: str):
    """Mark a shipment as delivered. The command comes from the path alone."""
    command = DeliverShipment(shipment_id=shipment_id)
    result = current_domain.process(command, asynchronous=False)
    return {"shipment_id": result, "status": "delivered"}


@router.put("/{shipment_id}/cancel")
def cancel_shipment(shipment_id: str, body: CancelShipmentRequest):
    """Cancel a shipment."""
    command = CancelShipment(shipment_id=shipment_id, reason=body.reason)
    result = current_domain.process(command, asynchronous=False)
    return {"shipment_id": result, "status": "cancelled"}


# --- App factory ---


def create_app(domain: Domain) -> FastAPI:
    """Build the FastAPI app for an initialized domain."""
    app = FastAPI(title="Shipments")
    app.add_middleware(DomainContextMiddleware, route_domain_map={"/": domain})
    register_exception_handlers(app)
    app.include_router(router)
    return app


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    domain.init(traverse=False)
    uvicorn.run(create_app(domain), host="127.0.0.1", port=8000)
