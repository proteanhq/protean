# Update-Aggregate Command Flow

## Overview

Use this pattern when the command acts on an aggregate that already exists in the system (e.g., cancelling a reservation, changing a user's email, closing a project). The handler loads the aggregate from the repository before modifying it.

## Walkthrough

### The Aggregate

The command acts on an existing `Reservation`:

```python
@domain.aggregate
class Reservation:
    reservation_id: Identifier(identifier=True)
    guest_name: String(required=True, max_length=200)
    status: String(default="confirmed")
    cancel_reason: String()

    def cancel(self, reason: str):
        if self.status == "cancelled":
            raise ValueError("Reservation is already cancelled")
        if self.status == "checked_in":
            raise ValueError("Cannot cancel after check-in")
        self.status = "cancelled"
        self.cancel_reason = reason
```

### The Command

```python
@domain.command(part_of="Reservation")
class CancelReservation:
    reservation_id: Identifier(required=True)
    reason: String(required=True)
```

The command always carries the aggregate's identifier, so the handler can load it.

### The Handler (Update Pattern)

```python
@domain.command_handler(part_of=Reservation)
class ReservationCommandHandler:
    @handle(CancelReservation)
    def handle_cancel_reservation(self, command: CancelReservation):
        reservation = domain.repository_for(Reservation).get(command.reservation_id)
        reservation.cancel(reason=command.reason)
        domain.repository_for(Reservation).add(reservation)
        return reservation.reservation_id
```

Persisting a modified aggregate uses the same `.add()` call as create.

### The Endpoint

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from protean import current_domain


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Wire the commands and handlers once, before the app takes requests
    domain.init()
    try:
        yield
    finally:
        # Release the adapter connections on shutdown, even after an error
        domain.close()


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def domain_context_middleware(request: Request, call_next):
    with domain.domain_context():
        return await call_next(request)


@app.put("/reservations/{reservation_id}/cancel")
async def cancel_reservation(reservation_id: str, request: Request):
    payload = await request.json()
    command = CancelReservation(
        reservation_id=reservation_id,   # from URL path
        reason=payload["reason"],        # from request body
    )
    result = current_domain.process(command, asynchronous=False)
    return JSONResponse(content={"reservation_id": result, "status": "cancelled"})
```

## Combining Path Parameters and Body

An update endpoint builds the command from both:

| Data source | What it provides | Example |
|-------------|------------------|---------|
| Path parameter | Resource identifier | `/reservations/{reservation_id}/cancel` |
| Request body | Action-specific data | `{"reason": "Change of plans"}` |

## Error Handling

When the aggregate's business method raises an error (e.g., "Cannot cancel after check-in"), the exception propagates through the handler and results in a server error. The UnitOfWork automatically rolls back, preventing partial state changes.

## Related

- [Create-aggregate flow](./create-aggregate-flow.md): For creating new aggregates
- [Multiple commands flow](./multiple-commands-flow.md): Adding many commands to one aggregate
