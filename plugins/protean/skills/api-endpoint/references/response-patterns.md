# Response Patterns

HTTP response structure and status codes for Protean API endpoints.

## Overview

Endpoints should return consistent, predictable HTTP responses. Since endpoints only translate domain results to HTTP, response logic stays simple.

## Status Code Guidelines

| Operation | Status Code | When |
|-----------|------------|------|
| Resource created | 201 Created | POST that creates a new aggregate |
| Action performed | 200 OK | PUT/POST that modifies existing state |
| Accepted for processing | 202 Accepted | Async command processing (fire-and-forget) |
| Validation error | 422 Unprocessable Entity | Pydantic validation fails (automatic) |

## Response Structure

### Synchronous Processing (asynchronous=False)

```python
@app.post("/orders", status_code=201)
async def create_order(request: Request):
    payload = await request.json()
    command = PlaceOrder(
        order_id=payload["order_id"],
        customer_id=payload["customer_id"],
        total_amount=payload["total_amount"],
    )
    result = current_domain.process(command, asynchronous=False)
    return JSONResponse(
        status_code=201,
        content={"order_id": result, "status": "placed"},
    )
```

The handler's return value (e.g., order ID) is available as `result`.

### Asynchronous Processing (default)

```python
@app.post("/events", status_code=202)
async def submit_event(request: Request):
    payload = await request.json()
    command = RecordEvent(event_id=payload["event_id"])
    position = current_domain.process(command)  # async by default
    return JSONResponse(
        status_code=202,
        content={"status": "accepted", "position": position},
    )
```

The return value is the position in the event store, not the handler result.

## Consistent JSON Shape

Adopt a consistent response envelope:

```python
# For creation
{"order_id": "ORD-001", "status": "placed"}

# For state change
{"order_id": "ORD-001", "status": "cancelled"}

# For async acceptance
{"status": "accepted", "position": 42}
```

Keep responses minimal. The endpoint's job is confirmation, not data retrieval.

## Error Responses

Domain errors propagate as exceptions. Handle them with FastAPI exception handlers if needed:

```python
from protean.exceptions import ObjectNotFoundError

@app.exception_handler(ObjectNotFoundError)
async def not_found_handler(request: Request, exc: ObjectNotFoundError):
    return JSONResponse(
        status_code=404,
        content={"error": "not_found", "message": str(exc)},
    )
```

## Related

- [Request Validation](./request-validation.md) - Input validation patterns
- [Testing Endpoints](./testing-endpoints.md) - Verifying response codes in tests
- [Anti-patterns](./anti-patterns.md) - Response anti-patterns
