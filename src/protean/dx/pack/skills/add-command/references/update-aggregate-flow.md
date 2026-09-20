# Update-Aggregate Command Flow

This reference explains the complete flow for adding a command that modifies an existing aggregate.

## Overview

Use this pattern when the command acts on an aggregate that already exists in the system (e.g., cancelling a reservation, changing a user's email, closing a project). The handler loads the aggregate from the repository before modifying it.

## Code

The complete implementation is in [assets/add_command_update_flow.py](../assets/add_command_update_flow.py).

Key highlights:
- Command carries the aggregate's identifier plus action-specific data
- Handler loads existing aggregate via `domain.repository_for(Aggregate).get(id)`
- Handler calls aggregate method, then persists the modified aggregate
- PUT endpoint uses path parameter for resource identification

## Walkthrough

### The Command

```python
@domain.command(part_of="Reservation")
class CancelReservation:
    reservation_id: Identifier(required=True)
    reason: String(required=True)
```

- Always includes the aggregate's identifier field so the handler can load it
- Additional fields carry data needed for the action

### The Handler (Update Pattern)

```python
@handle(CancelReservation)
def handle_cancel_reservation(self, command: CancelReservation):
    reservation = domain.repository_for(Reservation).get(command.reservation_id)
    reservation.cancel(reason=command.reason)
    domain.repository_for(Reservation).add(reservation)
    return reservation.reservation_id
```

The update pattern has four steps:
1. **Load** the aggregate from the repository using the identifier from the command
2. **Call** the aggregate method with data from the command
3. **Persist** the modified aggregate (same `.add()` method as create)
4. **Return** an identifier for the caller

### The Endpoint

```python
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

- HTTP PUT for actions on existing resources
- Combines path parameters (resource ID) with request body (action data)
- Uses `current_domain.process()` for synchronous processing

## Combining Path Parameters and Body

A common pattern for update commands:

| Data source | What it provides | Example |
|-------------|------------------|---------|
| Path parameter | Resource identifier | `/reservations/{reservation_id}/cancel` |
| Request body | Action-specific data | `{"reason": "Change of plans"}` |

The endpoint combines both when constructing the command.

## HTTP Verb Choice

| Operation | HTTP Method | Status Code | Example Route |
|-----------|-------------|-------------|---------------|
| Action on resource | PUT | 200 OK | `PUT /reservations/{id}/cancel` |
| Update resource | PUT | 200 OK | `PUT /users/{id}/email` |
| Action without body | PUT | 200 OK | `PUT /shipments/{id}/deliver` |

## Error Handling

When the aggregate's business method raises an error (e.g., "Cannot cancel after check-in"), the exception propagates through the handler and results in a server error. The UnitOfWork automatically rolls back, preventing partial state changes.

## Related

- [Create-aggregate flow](./create-aggregate-flow.md) - For creating new aggregates
- [Multiple commands flow](./multiple-commands-flow.md) - Adding many commands to one aggregate
