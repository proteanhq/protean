"""
Complete command flow for modifying an existing aggregate.

This example demonstrates the full add-command workflow for an update operation:
- Command class for an action on an existing aggregate (CancelReservation)
- Command handler that loads an existing aggregate from the repository
- FastAPI PUT endpoint with path parameter for resource identification
- Combining path parameters and request body data in command construction

Workflow:
    PUT /reservations/{id}/cancel → CancelReservation command → ReservationCommandHandler
    → load Reservation from repo → call cancel() → persist → return reservation_id

Usage:
    # First create a reservation
    curl -X POST http://localhost:8000/reservations \\
        -H "Content-Type: application/json" \\
        -d '{"reservation_id": "RES-001", "guest_name": "Alice", "room_type": "suite"}'

    # Then cancel it
    curl -X PUT http://localhost:8000/reservations/RES-001/cancel \\
        -H "Content-Type: application/json" \\
        -d '{"reason": "Change of plans"}'
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from protean import Domain, handle
from protean.fields import Identifier, String
from protean.utils.globals import current_domain

# Domain setup
domain = Domain()


@domain.aggregate
class Reservation:
    """Hotel reservation aggregate."""

    reservation_id: Identifier(identifier=True)
    guest_name: String(required=True, max_length=200)
    room_type: String(required=True)
    status: String(default="confirmed")
    cancel_reason: String()

    def cancel(self, reason: str):
        """Cancel the reservation with a reason.

        Business logic stays in the aggregate - the handler
        and endpoint should NOT duplicate this check.
        """
        if self.status == "cancelled":
            raise ValueError("Reservation is already cancelled")
        if self.status == "checked_in":
            raise ValueError("Cannot cancel after check-in")
        self.status = "cancelled"
        self.cancel_reason = reason


# --- Commands ---


@domain.command(part_of="Reservation")
class MakeReservation:
    """Command to create a new reservation."""

    reservation_id: Identifier(required=True)
    guest_name: String(required=True, max_length=200)
    room_type: String(required=True)


@domain.command(part_of="Reservation")
class CancelReservation:
    """Command to cancel an existing reservation.

    Requires the reservation ID (to find it) and a reason (business requirement).
    """

    reservation_id: Identifier(required=True)
    reason: String(required=True)


# --- Command Handler ---


@domain.command_handler(part_of=Reservation)
class ReservationCommandHandler:
    """Handler for reservation commands.

    Demonstrates both create and update patterns in one handler.
    """

    @handle(MakeReservation)
    def handle_make_reservation(self, command: MakeReservation):
        """Handle MakeReservation - creates a new aggregate."""
        reservation = Reservation(
            reservation_id=command.reservation_id,
            guest_name=command.guest_name,
            room_type=command.room_type,
        )
        domain.repository_for(Reservation).add(reservation)
        return reservation.reservation_id

    @handle(CancelReservation)
    def handle_cancel_reservation(self, command: CancelReservation):
        """Handle CancelReservation - loads and modifies existing aggregate.

        Update workflow:
        1. Load aggregate from repository using ID from command
        2. Call aggregate method with data from command
        3. Persist the modified aggregate (same .add() method)
        4. Return identifier
        """
        reservation = domain.repository_for(Reservation).get(command.reservation_id)
        reservation.cancel(reason=command.reason)
        domain.repository_for(Reservation).add(reservation)
        return reservation.reservation_id


# --- FastAPI Endpoints ---

app = FastAPI(title="Reservation API")


@app.middleware("http")
async def domain_context_middleware(request: Request, call_next):
    """Middleware to provide domain context for every request."""
    with domain.domain_context():
        response = await call_next(request)
    return response


@app.post("/reservations", status_code=201)
async def make_reservation(request: Request):
    """Create a new reservation.

    POST /reservations - all data from request body.
    """
    payload = await request.json()

    command = MakeReservation(
        reservation_id=payload["reservation_id"],
        guest_name=payload["guest_name"],
        room_type=payload["room_type"],
    )

    result = current_domain.process(command, asynchronous=False)

    return JSONResponse(
        status_code=201,
        content={"reservation_id": result, "status": "confirmed"},
    )


@app.put("/reservations/{reservation_id}/cancel")
async def cancel_reservation(reservation_id: str, request: Request):
    """Cancel an existing reservation.

    PUT /reservations/{id}/cancel - ID from path, reason from body.
    Demonstrates combining path parameters and request body in
    command construction.
    """
    payload = await request.json()

    command = CancelReservation(
        reservation_id=reservation_id,  # from URL path
        reason=payload["reason"],  # from request body
    )

    result = current_domain.process(command, asynchronous=False)

    return JSONResponse(
        content={"reservation_id": result, "status": "cancelled"},
    )


# Example usage
if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    domain.init(traverse=False)
    uvicorn.run(app, host="127.0.0.1", port=8000)
