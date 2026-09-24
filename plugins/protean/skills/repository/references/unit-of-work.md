# Unit of Work Integration

Repositories respect Protean's Unit of Work (UoW) pattern, which ensures that all changes within a business transaction are committed atomically — either everything succeeds, or nothing does.

## Overview

The Unit of Work tracks all changes made to aggregates during a transaction and commits them together at the end. In Protean:

- **Command handlers** have an **implicit UoW** — no manual wrapping needed
- **Outside handlers** (scripts, tests, migrations), you use an **explicit UoW**
- The UoW manages database sessions, ensures atomic commits, and handles rollbacks

## Code

The complete implementation is in [assets/repository_with_uow.py](../assets/repository_with_uow.py).

## Implicit UoW in Handlers

Command handlers and event handlers are automatically wrapped in a UoW:

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def handle_place_order(self, command):
        order = Order(order_id=command.order_id)
        order.place()
        domain.repository_for(Order).add(order)
        # UoW commits automatically when handler completes
        # If an exception occurs, UoW rolls back automatically
```

**Key point**: Do NOT wrap handler methods in `with UnitOfWork()` — the framework handles this.

## Explicit UoW Outside Handlers

When working outside handler methods (e.g., scripts, test setup, data migrations), use the UoW as a context manager:

```python
from protean.core.unit_of_work import UnitOfWork

with UnitOfWork():
    repo = domain.repository_for(Account)
    account = repo.get("ACC-001")
    account.deposit(500.0)
    repo.add(account)
# Changes are committed when exiting the `with` block
```

### Manual Start/Commit

For more control:

```python
uow = UnitOfWork()
uow.start()
try:
    repo = domain.repository_for(Account)
    account = Account(account_id="ACC-002", holder_name="Bob")
    repo.add(account)
    uow.commit()
except Exception:
    uow.rollback()
    raise
```

## How Repository Operations Interact with UoW

### Inside a UoW

When a UoW is active:
1. `repo.add(aggregate)` stages the change in the UoW's session
2. Changes are NOT written to the database yet
3. On `uow.commit()`, all staged changes are written atomically
4. On `uow.rollback()`, all staged changes are discarded

### Outside a UoW

When no UoW is active:
1. `repo.add(aggregate)` creates its own mini-UoW internally
2. The change is committed immediately
3. Each `add()` call is an independent transaction

## Identity Map

The UoW maintains an **identity map** — a cache of aggregates seen during the transaction. This ensures:
- The same aggregate loaded twice returns the same object
- Events raised by aggregates are collected and dispatched at commit time
- Optimistic concurrency checks are performed at commit time

## Transactional Guarantees

| Scenario | Behavior |
|----------|----------|
| Handler succeeds | All changes committed atomically |
| Handler raises exception | All changes rolled back |
| Multiple `repo.add()` calls | All committed together |
| Events raised during handler | Dispatched after successful commit |
| Optimistic concurrency conflict | `ExpectedVersionError` raised, changes rolled back |

## Related
- [Default Repository](./default-repository.md) - Repository fundamentals
- [Custom Queries](./custom-queries.md) - Query methods
- [Anti-patterns](./anti-patterns.md) - Common UoW mistakes
