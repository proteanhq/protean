---
name: api-endpoint
description: Define FastAPI API endpoints for a Protean application. Endpoints are thin adapters at the domain boundary that translate HTTP requests into domain commands and hand them off via domain.process(). They contain NO business logic. Use when you need to create an API endpoint, define a route, add a REST endpoint, expose a command via HTTP, build a FastAPI handler, connect HTTP to the domain, create a POST/PUT/DELETE endpoint, or wire an HTTP request to a domain command.
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework, fastapi
metadata:
  author: proteanhq
  version: "0.1"
  category: element
---

# API Endpoint

## Basic structure

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from protean.utils.globals import current_domain

app = FastAPI()

@app.middleware("http")
async def domain_context_middleware(request: Request, call_next):
    with domain.domain_context():
        response = await call_next(request)
    return response

@app.post("/orders", status_code=201)
async def create_order(request: Request):
    payload = await request.json()
    command = PlaceOrder(
        order_id=payload["order_id"],
        customer_id=payload["customer_id"],
        total_amount=payload["total_amount"],
    )
    result = current_domain.process(command, asynchronous=False)
    return JSONResponse(status_code=201, content={"order_id": result})
```

## Key rules

1. **Endpoints are thin adapters** - Only translate HTTP to commands. NO business logic, NO repository access, NO aggregate manipulation
2. **Always use domain context middleware** - Every request must run inside `domain.domain_context()` so `current_domain` is available
3. **Use `current_domain.process()`** - Never call handlers directly. Always submit commands through `domain.process()`
4. **Construct commands from payload** - Map request body fields (and path parameters) to command fields
5. **Use `asynchronous=False` for sync** - Call `domain.process(command, asynchronous=False)` when you need the result immediately
6. **Return appropriate status codes** - 201 for creation, 200 for updates, match HTTP semantics
7. **Import `current_domain` from globals** - `from protean.utils.globals import current_domain`
8. **Pydantic models for validation** - Use Pydantic `BaseModel` subclasses as FastAPI request bodies for automatic input validation (422 on invalid data)

## Endpoint patterns

| Pattern | HTTP Method | Example | Command Source |
|---------|------------|---------|----------------|
| Create resource | POST | `POST /orders` | Body only |
| Action on resource | PUT | `PUT /orders/{id}/cancel` | Path + Body |
| Action without body | PUT | `PUT /shipments/{id}/deliver` | Path only |
| Validated create | POST | `POST /accounts/register` | Pydantic model |

## Quick example: Path parameters

```python
@app.put("/orders/{order_id}/cancel")
async def cancel_order(order_id: str, request: Request):
    payload = await request.json()
    command = CancelOrder(
        order_id=order_id,        # from URL path
        reason=payload["reason"],  # from request body
    )
    result = current_domain.process(command, asynchronous=False)
    return JSONResponse(content={"order_id": result, "status": "cancelled"})
```

## Quick example: Pydantic validation

```python
from pydantic import BaseModel, Field

class RegisterAccountRequest(BaseModel):
    account_id: str = Field(..., min_length=1)
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str = Field(..., min_length=1, max_length=100)

@app.post("/accounts/register", status_code=201)
async def register_account(body: RegisterAccountRequest):
    command = RegisterAccount(
        account_id=body.account_id,
        email=body.email,
        name=body.name,
    )
    result = current_domain.process(command, asynchronous=False)
    return JSONResponse(status_code=201, content={"account_id": result})
```

## Sync vs async processing

```python
# Synchronous - blocks, returns handler result
result = current_domain.process(command, asynchronous=False)

# Asynchronous (default) - returns position in event store
position = current_domain.process(command)
```

Use `asynchronous=False` when the endpoint needs to return data from the handler (e.g., created resource ID). Use the default (async) for fire-and-forget operations.

## Common mistakes

### Business logic in the endpoint

```python
# Wrong! Business logic belongs in the aggregate
@app.post("/orders")
async def create_order(request: Request):
    payload = await request.json()
    if payload["total_amount"] <= 0:  # Business rule in endpoint!
        return JSONResponse(status_code=400, content={"error": "Invalid amount"})
```

Instead: Let the aggregate enforce business rules. The endpoint only constructs the command.

### Accessing repositories directly

```python
# Wrong! Endpoints should not access repositories
@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    order = current_domain.repository_for(Order).get(order_id)  # Direct repo access!
```

Instead: Use commands and `domain.process()` for all write operations. For reads, use query/projection patterns.

### Missing domain context middleware

```python
# Wrong! current_domain will not be available without middleware
@app.post("/orders")
async def create_order(request: Request):
    current_domain.process(command)  # RuntimeError: no domain context!
```

Instead: Always register the domain context middleware on the app.

### Calling handlers directly

```python
# Wrong! Never bypass domain.process()
@app.post("/orders")
async def create_order(request: Request):
    handler = OrderCommandHandler()
    handler.handle_place_order(command)  # Bypasses enrichment and event store!
```

Instead: Always use `current_domain.process(command)`.

## Detailed references

### Concepts
- [Request Validation](references/request-validation.md) - Pydantic models for input validation
- [Response Patterns](references/response-patterns.md) - HTTP response structure and status codes
- [Testing Endpoints](references/testing-endpoints.md) - Using TestClient for endpoint tests
- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

### Complete Examples
- [Simple POST](assets/api_endpoint_simple.py) - Basic POST endpoint with synchronous processing
- [Path Parameters](assets/api_endpoint_path_params.py) - Endpoints with URL path parameters
- [Pydantic Validation](assets/api_endpoint_with_pydantic.py) - Request validation with Pydantic models
- [Complete Router](assets/api_endpoint_complete_router.py) - Full router with multiple endpoints for one aggregate

### Related Skills
- `command` - Commands are what endpoints construct
- `command-handler` - Command handlers process the commands that endpoints submit
- `aggregate` - The target of commands submitted through endpoints

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
