# Handle Domain Errors

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

A domain exception starts at an aggregate invariant and ends as an API
response. Here is how to raise one, how it propagates, and where to handle it
along the way.

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
--8<-- "guides/domain-behavior/error-handling/001.py:invariant"
```

### From domain methods

Use `InvalidStateError` or `InvalidOperationError` for explicit
business logic checks:

```python
--8<-- "guides/domain-behavior/error-handling/002.py:cancel"
```

---

## Error propagation through layers

Protean exceptions propagate naturally, don't catch them in handlers or
services unless you need to translate them:

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
--8<-- "guides/domain-behavior/error-handling/003.py:handler"
```

### In application services

Same principle, let domain exceptions propagate to the caller:

```python
--8<-- "guides/domain-behavior/error-handling/003.py:service"
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
--8<-- "guides/domain-behavior/error-handling/003.py:repository"
```

---

## Unit of Work errors

Transaction failures during `UnitOfWork.commit()` raise:

- **`ExpectedVersionError`**: Optimistic concurrency conflict in
  event-sourced aggregates. The client should retry with fresh state.
- **`TransactionError`**: Wraps the underlying database error. The
  original exception is available as `exc.__cause__`.

---

## Mapping to HTTP responses

Use `register_exception_handlers` to automatically map domain exceptions
to HTTP status codes in FastAPI:

```python
--8<-- "guides/domain-behavior/error-handling/003.py:fastapi"
```

| Exception | HTTP Status | Response body |
|-----------|:-----------:|---------------|
| `ValidationError` | 400 | `{"error": {"field": ["message"]}}` |
| `InvalidDataError` | 400 | `{"error": {"field": ["message"]}}` |
| `ValueError` | 400 | `{"error": "message"}` |
| `ObjectNotFoundError` | 404 | `{"error": "message"}` |
| `InvalidStateError` | 409 | `{"error": "message"}` |
| `InvalidOperationError` | 422 | `{"error": "message"}` |

When a domain context is active, the response body also carries a
`correlation_id` that matches the `X-Correlation-ID` response header.

Your endpoints don't need try/except blocks:

```python
--8<-- "guides/domain-behavior/error-handling/003.py:endpoint"
```

See [FastAPI Integration](../fastapi/index.md) for full setup.

---

## Testing error conditions

Use `pytest.raises`:

```python
--8<-- "guides/domain-behavior/error-handling/003.py:test"
```

---

!!! seealso "See also"
    - [Invariants](./invariants.md): How to define business rules.
    - [Classify Async Processing Errors](../../patterns/classify-async-processing-errors.md):
      Error handling in event handlers and projectors.
    - [FastAPI Integration](../fastapi/index.md): Exception handler setup.
