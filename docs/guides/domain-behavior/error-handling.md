# Handle Domain Errors

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

This guide covers how to raise, propagate, and handle domain exceptions
in Protean -- from aggregate invariants through command handlers to
API responses.

---

## Exception hierarchy

Protean provides domain-specific exceptions that propagate naturally
through the application layers:

| Exception | When to use | Typical HTTP mapping |
|-----------|-------------|:--------------------:|
| `ValidationError` | Invariant violation, field validation failure | 400 |
| `InvalidDataError` | Data type or value mismatch | 400 |
| `ObjectNotFoundError` | Aggregate not found in persistence | 404 |
| `InvalidStateError` | Operation invalid for current aggregate state | 409 |
| `InvalidOperationError` | Business rule prevents the operation | 422 |
| `ExpectedVersionError` | Optimistic concurrency conflict (ES) | 409 |

---

## Raising errors in aggregates

### From invariants

Invariants raise `ValidationError` when business rules are violated.
The error dict uses `"_entity"` as the key for aggregate-level errors:

```python
from protean.exceptions import ValidationError

@domain.aggregate
class Order:
    items = HasMany("OrderItem")
    status = String(default="draft")

    @invariant.post
    def must_have_items(self):
        if not self.items:
            raise ValidationError(
                {"_entity": ["Order must contain at least one item"]}
            )
```

### From domain methods

Use `InvalidStateError` or `InvalidOperationError` for explicit
business logic checks:

```python
from protean.exceptions import InvalidStateError

@domain.aggregate
class Order:
    status = String(default="draft")

    def cancel(self):
        if self.status == "shipped":
            raise InvalidStateError("Cannot cancel a shipped order")
        self.status = "cancelled"
```

---

## Error propagation through layers

Protean exceptions propagate naturally -- don't catch them in handlers
or services unless you need to translate them:

```
Aggregate method
  └── raises ValidationError / InvalidStateError
        └── propagates through Command Handler
              └── propagates through domain.process()
                    └── propagates through API endpoint
                          └── mapped to HTTP response by exception handler
```

### In command handlers

Let exceptions propagate. Don't wrap them:

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command):
        order = Order(
            customer_id=command.customer_id,
            items=command.items,  # ValidationError if empty
        )
        order.place()  # InvalidStateError if invalid transition
        current_domain.repository_for(Order).add(order)
```

### In application services

Same principle -- let domain exceptions propagate to the caller:

```python
@domain.application_service(part_of=Order)
class OrderService:
    @use_case
    def place_order(self, customer_id, items):
        order = Order(customer_id=customer_id, items=items)
        order.place()
        current_domain.repository_for(Order).add(order)
        return order.id
```

---

## Repository errors

| Method | Raises | When |
|--------|--------|------|
| `repo.get(id)` | `ObjectNotFoundError` | ID not found |
| `repo.find_by(**kwargs)` | `ObjectNotFoundError` | No match found |
| `repo.find_by(**kwargs)` | `TooManyObjectsError` | Multiple matches |
| `repo.find(criteria)` | *(never)* | Returns empty `ResultSet` |
| `repo.exists(criteria)` | *(never)* | Returns `bool` |

Use `repo.find()` or `repo.exists()` when absence is expected, and
`repo.get()` when absence is an error:

```python
# Absence is an error -- let it raise
order = repo.get(order_id)  # ObjectNotFoundError → 404

# Absence is expected -- check gracefully
if repo.exists(Q(email=email)):
    raise InvalidOperationError("Email already registered")
```

---

## Unit of Work errors

Transaction failures during `UnitOfWork.commit()` raise:

- **`ExpectedVersionError`** -- optimistic concurrency conflict in
  event-sourced aggregates. The client should retry with fresh state.
- **`TransactionError`** -- wraps the underlying database error. The
  original exception is available as `exc.__cause__`.

---

## Mapping to HTTP responses

Use `register_exception_handlers` to automatically map domain exceptions
to HTTP status codes in FastAPI:

```python
from protean.integrations.fastapi import register_exception_handlers

app = FastAPI()
register_exception_handlers(app)
```

| Exception | HTTP Status | Response body |
|-----------|:-----------:|---------------|
| `ValidationError` | 400 | `{"error": {"field": ["message"]}}` |
| `InvalidDataError` | 400 | `{"error": {"field": ["message"]}}` |
| `ValueError` | 400 | `{"error": "message"}` |
| `ObjectNotFoundError` | 404 | `{"error": "message"}` |
| `InvalidStateError` | 409 | `{"error": "message"}` |
| `InvalidOperationError` | 422 | `{"error": "message"}` |

Your endpoints don't need try/except blocks:

```python
@app.post("/orders", status_code=201)
async def place_order(payload: dict):
    # ValidationError → 400, ObjectNotFoundError → 404, etc.
    current_domain.process(PlaceOrder(**payload))
    return {"status": "accepted"}
```

See [FastAPI Integration](../fastapi/index.md) for full setup.

---

## Testing error conditions

Use `pytest.raises`:

```python
import pytest
from protean.exceptions import ValidationError

def test_order_requires_items():
    with pytest.raises(ValidationError) as exc:
        Order(customer_id="c1", items=[])
    assert "must contain at least one item" in str(exc.value)
```

---

!!! tip "See also"
    - [Invariants](./invariants.md) -- How to define business rules.
    - [Classify Async Processing Errors](../../patterns/classify-async-processing-errors.md)
      -- Error handling in event handlers and projectors.
    - [FastAPI Integration](../fastapi/index.md) -- Exception handler setup.
