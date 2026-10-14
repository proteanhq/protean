# Unit of Work Integration

Repositories respect Protean's Unit of Work (UoW) pattern. On a provider with transactions, all changes within a Unit of Work commit together, or none of them does.

## Overview

On a provider with transactions, such as the SQL databases, a Unit of Work is one real database transaction. It can hold changes to several aggregates; "one aggregate per transaction" is a design rule you keep, and the Unit of Work does not enforce it. In Protean:

- **Command handlers and event handlers** have an **implicit UoW**: `@handle` wraps every handler call in its own Unit of Work, so no manual wrapping is needed
- **Outside handlers** (scripts, tests, migrations), you use an **explicit UoW**
- The UoW manages database sessions, commits, and rollbacks

Commits and rollbacks are atomic on providers with real transactions, such as the SQL providers ADR-0027 covers. The in-memory provider keeps writes in the Unit of Work until it commits, so a rollback also leaves nothing behind. Elasticsearch has no transactions. There the Unit of Work logs a warning that commit and rollback are not atomic, and a rollback does not undo writes already sent.

## Code

The complete implementation is in [assets/repository_with_uow.py](../assets/repository_with_uow.py).

The design is recorded in ADR-0027 ([The Unit of Work is a real database transaction](https://docs.proteanhq.com/adr/0027-unit-of-work-is-a-real-transaction/)) and ADR-0031 ([A handler method persists or calls out, never both](https://docs.proteanhq.com/adr/0031-handlers-persist-or-call-out/)).

## Implicit UoW in Handlers

The examples on this page use these aggregates and this command:

```python
@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    status: String(max_length=20, default="draft")

    def place(self):
        self.status = "placed"


@domain.command(part_of=Order)
class PlaceOrder:
    order_id: Identifier(identifier=True)


@domain.aggregate
class Account:
    account_id: Identifier(identifier=True)
    holder_name: String(required=True, max_length=100)
    balance: Float(default=0.0)

    def deposit(self, amount):
        self.balance += amount
```

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

**Key point**: Do NOT wrap handler code in `with UnitOfWork()`. A Unit of Work started while another is active joins the outer one, so the inner block opens no transaction of its own and its commit and rollback defer to the handler's.

## Explicit UoW Outside Handlers

When working outside handler methods (e.g., scripts, test setup, data migrations), use the UoW as a context manager:

```python
from protean.core.unit_of_work import UnitOfWork

domain.init(traverse=False)

with domain.domain_context():
    domain.repository_for(Account).add(
        Account(account_id="ACC-001", holder_name="Alice")
    )

with domain.domain_context(), UnitOfWork():
    repo = domain.repository_for(Account)
    account = repo.get("ACC-001")
    account.deposit(500.0)
    repo.add(account)
# Changes are committed when exiting the `with` block
```

### Manual Start/Commit

For more control:

```python
with domain.domain_context():
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
1. `repo.add(aggregate)` writes the change through the UoW's session, inside the open transaction
2. Reads in the same UoW see the write (the session flushes before it queries), but nothing is committed or visible to other connections yet
3. On `uow.commit()`, the transaction commits and every change becomes visible together
4. On `uow.rollback()`, the transaction rolls back and every change is undone

### Outside a UoW

When no UoW is active:
1. `repo.add(aggregate)` creates its own mini-UoW internally
2. The change is committed immediately
3. Each `add()` call is an independent transaction

## Identity Map

The UoW keeps an **identity map**: one instance of each aggregate it loads or saves during the transaction. At commit it collects the events those aggregates raised and dispatches them. Once an aggregate is in the map, a `get()` or query of the same id in that UoW returns the same object, with any changes made to it since. This holds for state-based and event-sourced aggregates. A temporal query on an event-sourced aggregate (`at_version` or `as_of`) does not use the map.

## Transactional Guarantees

| Scenario | Behavior |
|----------|----------|
| Handler succeeds | All changes committed together (atomic on providers with transactions) |
| Handler raises exception | All changes rolled back (on Elasticsearch, writes already sent stay) |
| Multiple `repo.add()` calls | All committed together |
| Events raised during handler | Dispatched after successful commit |
| Optimistic concurrency conflict | `ExpectedVersionError` raised, changes rolled back. `@handle` re-runs the whole handler body: with the default `max_retries=3`, the body runs up to 4 times in total |

## Retries on Version Conflicts

On a version conflict, `@handle` re-runs the whole handler body. The default is `max_retries=3`, so the body runs up to 4 times in total. The wait between runs doubles each time, from 0.05 seconds up to a cap of 1 second. The retries stop early if the next run would start after the command's deadline. Change these settings, or turn the retry off, under `server.version_retry` in the domain config.

Each run opens its own Unit of Work. When the handler runs inside an outer Unit of Work, for example a use case that calls `domain.process()` synchronously, every run joins that outer one. The first failed run has already doomed the outer transaction, so the later runs cannot save it.

`@use_case` in an application service does not retry. It runs the method once.

## Related
- [Default Repository](./default-repository.md) - Repository fundamentals
- [Custom Queries](./custom-queries.md) - Query methods
- [Anti-patterns](./anti-patterns.md) - Common UoW mistakes
