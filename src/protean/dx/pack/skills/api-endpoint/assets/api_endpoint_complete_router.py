"""
Complete FastAPI router with multiple endpoints for one aggregate.

This example demonstrates:
- A full FastAPI router with CRUD-style operations mapped to domain commands
- Multiple endpoints for the same aggregate (create, update status, cancel)
- Both POST and PUT verbs for different command types
- Path parameters combined with request bodies
- Consistent JSON response structure across all endpoints
- Domain context middleware pattern

Usage:
    # Start the server
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

    # Cancel shipment
    curl -X PUT http://localhost:8000/shipments/SHP-001/cancel \\
        -H "Content-Type: application/json" \\
        -d '{"reason": "Customer changed address"}'
"""

from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from protean import Domain, handle
from protean.fields import DateTime, Float, Identifier, String
from protean.utils.globals import current_domain

# Domain setup
domain = Domain()


@domain.aggregate
class Shipment:
    """Shipment aggregate with full lifecycle operations."""

    shipment_id: Identifier(identifier=True)
    origin: String(required=True)
    destination: String(required=True)
    weight: Float(required=True)
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
            raise ValueError(f"Cannot update tracking for '{self.status}' shipment")
        self.tracking_number = tracking_number
        self.carrier = carrier
        self.status = "in_transit"

    def deliver(self):
        """Mark shipment as delivered."""
        if self.status != "in_transit":
            raise ValueError(f"Cannot deliver shipment in '{self.status}' status")
        self.status = "delivered"
        self.delivered_at = datetime.now(UTC)

    def cancel(self, reason: str):
        """Cancel the shipment."""
        if self.status in ("delivered", "cancelled"):
            raise ValueError(f"Cannot cancel shipment in '{self.status}' status")
        self.status = "cancelled"
        self.cancelled_at = datetime.now(UTC)
        self.cancel_reason = reason


# --- Commands ---


@domain.command(part_of="Shipment")
class CreateShipment:
    """Command to create a new shipment."""

    shipment_id: Identifier(required=True)
    origin: String(required=True)
    destination: String(required=True)
    weight: Float(required=True)


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
        domain.repository_for(Shipment).add(shipment)
        return shipment.shipment_id

    @handle(UpdateTracking)
    def handle_update_tracking(self, command: UpdateTracking):
        """Update tracking on an existing shipment."""
        shipment = domain.repository_for(Shipment).get(command.shipment_id)
        shipment.update_tracking(
            tracking_number=command.tracking_number,
            carrier=command.carrier,
        )
        domain.repository_for(Shipment).add(shipment)
        return shipment.shipment_id

    @handle(DeliverShipment)
    def handle_deliver(self, command: DeliverShipment):
        """Mark a shipment as delivered."""
        shipment = domain.repository_for(Shipment).get(command.shipment_id)
        shipment.deliver()
        domain.repository_for(Shipment).add(shipment)
        return shipment.shipment_id

    @handle(CancelShipment)
    def handle_cancel(self, command: CancelShipment):
        """Cancel a shipment."""
        shipment = domain.repository_for(Shipment).get(command.shipment_id)
        shipment.cancel(reason=command.reason)
        domain.repository_for(Shipment).add(shipment)
        return shipment.shipment_id


# --- FastAPI app with complete router ---

app = FastAPI(title="Complete Shipment Router Example")


@app.middleware("http")
async def domain_context_middleware(request: Request, call_next):
    """Middleware to provide domain context for every request."""
    with domain.domain_context():
        response = await call_next(request)
    return response


@app.post("/shipments", status_code=201)
async def create_shipment(request: Request):
    """Create a new shipment.

    POST /shipments with JSON body containing shipment details.
    """
    payload = await request.json()

    command = CreateShipment(
        shipment_id=payload["shipment_id"],
        origin=payload["origin"],
        destination=payload["destination"],
        weight=payload["weight"],
    )

    result = current_domain.process(command, asynchronous=False)

    return JSONResponse(
        status_code=201,
        content={"shipment_id": result, "status": "created"},
    )


@app.put("/shipments/{shipment_id}/tracking")
async def update_tracking(shipment_id: str, request: Request):
    """Update tracking information for a shipment.

    PUT /shipments/{shipment_id}/tracking with tracking details.
    Path parameter identifies the shipment; body provides tracking data.
    """
    payload = await request.json()

    command = UpdateTracking(
        shipment_id=shipment_id,
        tracking_number=payload["tracking_number"],
        carrier=payload["carrier"],
    )

    result = current_domain.process(command, asynchronous=False)

    return JSONResponse(
        content={"shipment_id": result, "status": "in_transit"},
    )


@app.put("/shipments/{shipment_id}/deliver")
async def deliver_shipment(shipment_id: str):
    """Mark a shipment as delivered.

    PUT /shipments/{shipment_id}/deliver with no body needed.
    Only the path parameter is used to construct the command.
    """
    command = DeliverShipment(shipment_id=shipment_id)

    result = current_domain.process(command, asynchronous=False)

    return JSONResponse(
        content={"shipment_id": result, "status": "delivered"},
    )


@app.put("/shipments/{shipment_id}/cancel")
async def cancel_shipment(shipment_id: str, request: Request):
    """Cancel a shipment.

    PUT /shipments/{shipment_id}/cancel with cancellation reason in body.
    """
    payload = await request.json()

    command = CancelShipment(
        shipment_id=shipment_id,
        reason=payload["reason"],
    )

    result = current_domain.process(command, asynchronous=False)

    return JSONResponse(
        content={"shipment_id": result, "status": "cancelled"},
    )


# Example usage
if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    domain.init(traverse=False)
    uvicorn.run(app, host="127.0.0.1", port=8000)
