---
name: add-command
description: Add a complete command flow to an existing aggregate - creates a command class, a FastAPI API endpoint, and a command handler with repository logic. This is the primary workflow for adding write operations to a Protean domain. Use when the user wants to "add a command", "add an action", "add an operation", "expose a write endpoint", "create a command flow", "wire up a POST endpoint", "add a new operation to an aggregate", or describes an action like "I want users to be able to [verb] a [thing]" (e.g., "place an order", "register a user", "cancel a reservation"). This workflow composes the command, command-handler, and api-endpoint element skills.
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework, fastapi
metadata:
  author: proteanhq
  version: "0.1"
  category: workflow
  composes: [command, command-handler, api-endpoint]
---

# Add Command Flow

This workflow adds a complete command flow to an existing aggregate. It creates three artifacts that work together:

1. **Command** - An immutable DTO expressing intent (e.g., `PlaceOrder`)
2. **API Endpoint** - A thin FastAPI adapter that accepts HTTP payloads and submits commands
3. **Command Handler** - Orchestrates aggregate creation/loading, method invocation, and persistence

## What this creates

| Artifact | Role | File location |
|----------|------|---------------|
| Command class | Carries intent data | `<aggregate_folder>/<verb>_<noun>.py` |
| Command Handler | Loads/creates aggregate, calls methods, persists | Same file as command |
| API Endpoint | Translates HTTP to command, calls `domain.process()` | `<aggregate_folder>/<noun>_api.py` |

## Information to gather

Before generating, ensure you know the following. **If any item is unknown, ask the user before proceeding.**

- [ ] **Which aggregate** the command targets (must already exist)
- [ ] **Action name** (imperative verb + noun, e.g., PlaceOrder, CancelReservation)
- [ ] **Command fields** (the data needed to perform the action)
- [ ] **Create vs. Update** - Does this create a new aggregate or modify an existing one?
- [ ] **Aggregate method** - What method on the aggregate performs the business logic?
- [ ] **HTTP verb and route** - POST for creation, PUT for updates/actions

### Questions to ask when context is missing

If the user says "add a command to Order" without further detail, ask:

1. **"What action should this command represent?"** - e.g., "place an order", "cancel an order", "update shipping address"
2. **"What data does this action need?"** - e.g., order_id, customer_id, items list, reason
3. **"Does this create a new aggregate instance or modify an existing one?"** - determines create vs. update pattern, POST vs. PUT
4. **"What should the API route look like?"** - e.g., POST /orders, PUT /orders/{id}/cancel

If the user describes a full scenario like "I want users to be able to place an order with items and a total", you can infer:
- Action: PlaceOrder
- Create pattern (POST /orders, status 201)
- Fields: order_id, customer_id, items, total_amount
- Aggregate method: `place()` on Order

## Process

### Step 1: Define the Command

Follow the patterns in [command](../command/SKILL.md).

Key points for this workflow:
- Name with imperative verb: `PlaceOrder`, `RegisterUser`, `CancelReservation`
- Always specify `part_of="AggregateName"` (string, not class reference)
- Include all fields the handler needs (IDs, data fields)
- Commands are DTOs - only simple fields and value objects, no `HasOne`/`HasMany`

```python
@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    customer_id: String(required=True)
    total_amount: Float(required=True)
```

### Step 2: Define the Command Handler

Follow the patterns in [command-handler](../command-handler/SKILL.md).

Key points for this workflow:
- Use `part_of=AggregateClass` (class reference, not string)
- Use `@handle(CommandClass)` decorator on handler methods
- **Creating aggregates**: Construct from command data, call method, persist with `domain.repository_for(Aggregate).add()`
- **Updating aggregates**: Load with `domain.repository_for(Aggregate).get(id)`, call method, persist
- Return the aggregate's identifier for synchronous processing
- Each handler runs within an implicit UnitOfWork - no manual wrapping

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def handle_place_order(self, command: PlaceOrder):
        order = Order(
            order_id=command.order_id,
            customer_id=command.customer_id,
        )
        order.place(total_amount=command.total_amount)
        domain.repository_for(Order).add(order)
        return order.order_id
```

### Step 3: Define the API Endpoint

Follow the patterns in [api-endpoint](../api-endpoint/SKILL.md).

Key points for this workflow:
- Endpoint is a thin adapter - NO business logic
- Always set up domain context middleware
- Construct command from request payload (and path parameters)
- Use `current_domain.process(command, asynchronous=False)` for synchronous processing
- Return appropriate HTTP status codes (201 for creation, 200 for updates)

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
    return JSONResponse(status_code=201, content={"order_id": result})
```

### Step 4: Wire together

All three components connect through the domain:
1. API endpoint constructs command and calls `current_domain.process()`
2. Domain dispatches command to the matching handler (based on `part_of` and `@handle`)
3. Handler loads/creates aggregate, calls methods, persists via repository

```
HTTP Request → API Endpoint → Command → domain.process() → Command Handler
                                                              ↓
                                                         Load/Create Aggregate
                                                              ↓
                                                         Call Aggregate Method
                                                              ↓
                                                         repository.add(aggregate)
                                                              ↓
                                                         Return result
```

## File organization (Screaming Architecture)

Colocate command + handler in a single file named after the action. Place API endpoints in a separate `<aggregate>_api.py` file:

```
src/myapp/order/
├── order.py              # Aggregate + entities + VOs
├── place_order.py        # PlaceOrder command + OrderCommandHandler
├── cancel_order.py       # CancelOrder command (add to existing handler or new file)
└── order_api.py          # All API endpoints for Order
```

## Adding to an existing handler

When the aggregate already has a command handler, add the new `@handle` method to the existing handler class rather than creating a second one. Protean enforces one handler per command but allows multiple `@handle` methods in one handler class.

```python
# In place_order.py - add new command and handler method
@domain.command(part_of="Order")
class CancelOrder:
    order_id: Identifier(required=True)
    reason: String(required=True)

# Add to existing handler
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def handle_place_order(self, command): ...

    @handle(CancelOrder)
    def handle_cancel(self, command: CancelOrder):
        order = domain.repository_for(Order).get(command.order_id)
        order.cancel(reason=command.reason)
        domain.repository_for(Order).add(order)
```

## Key rules

1. **Commands use `part_of="String"`**, handlers use `part_of=ClassRef` (a string reference on a handler also works, resolved lazily at `init`; the class is just the usual convention when it is in scope) - don't mix them up
2. **One handler per command** - Protean enforces this; multiple `@handle` methods in one handler is fine
3. **Implicit UnitOfWork** - Do NOT wrap handler methods in manual UnitOfWork
4. **Endpoints are thin** - Only construct commands and call `domain.process()`. No repository access, no business logic
5. **Always use `current_domain.process()`** in endpoints - Never call handlers directly
6. **Domain context middleware is required** - Without it, `current_domain` is not available
7. **Return values** - Handler returns go back to the caller when using `asynchronous=False`

## Common mistakes

- **Business logic in the endpoint** - Move it to the aggregate
- **Repository access in the endpoint** - Only handlers access repositories
- **Manual UnitOfWork in handlers** - It's implicit, don't wrap
- **Calling handlers directly** - Always use `domain.process()`
- **Missing domain context middleware** - `current_domain` won't work without it
- **Two handlers for the same command** - Protean raises an error

## Complete examples

- [Create-aggregate command flow](references/create-aggregate-flow.md) - Full flow for creating a new aggregate (POST)
- [Update-aggregate command flow](references/update-aggregate-flow.md) - Full flow for modifying an existing aggregate (PUT)
- [Multiple commands flow](references/multiple-commands-flow.md) - Adding multiple commands to one aggregate

### Asset files
- [add_command_create_flow.py](assets/add_command_create_flow.py) - Complete create-aggregate flow with endpoint
- [add_command_update_flow.py](assets/add_command_update_flow.py) - Complete update-aggregate flow with endpoint
- [add_command_multiple_commands.py](assets/add_command_multiple_commands.py) - Multiple commands with shared handler and router

## Related skills

- [command](../command/SKILL.md) — Command definition, fields, and naming
- [command-handler](../command-handler/SKILL.md) — Handling commands and orchestrating aggregates
- [api-endpoint](../api-endpoint/SKILL.md) — Exposing commands over HTTP

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
