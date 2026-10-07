# Event-Sourced Repository

Event-sourced aggregates use a specialized repository that persists events to an event store instead of saving current state to a database.

## Setup

The examples on this page use a standard `Product` aggregate and an event-sourced `Account` aggregate:

```python
from protean.core.aggregate import apply
from protean.fields import Float, Identifier, String

@domain.aggregate
class Product:
    name: String(required=True)

@domain.event(part_of="Account")
class AccountOpened:
    account_id: Identifier(required=True)
    owner_name: String(required=True)
    balance: Float(required=True)

@domain.event(part_of="Account")
class MoneyDeposited:
    account_id: Identifier(required=True)
    amount: Float(required=True)

@domain.event(part_of="Account")
class MoneyWithdrawn:
    account_id: Identifier(required=True)
    amount: Float(required=True)

@domain.aggregate(event_sourced=True)
class Account:
    account_id: Identifier(identifier=True)
    owner_name: String(required=True)
    balance: Float(default=0.0)

    @classmethod
    def open(cls, account_id, owner_name, balance):
        account = cls(account_id=account_id, owner_name=owner_name, balance=balance)
        account.raise_(
            AccountOpened(account_id=account_id, owner_name=owner_name, balance=balance)
        )
        return account

    def deposit(self, amount):
        self.raise_(MoneyDeposited(account_id=self.account_id, amount=amount))

    def withdraw(self, amount):
        self.raise_(MoneyWithdrawn(account_id=self.account_id, amount=amount))

    @apply
    def opened(self, event: AccountOpened):
        self.account_id = event.account_id
        self.owner_name = event.owner_name
        self.balance = event.balance

    @apply
    def deposited(self, event: MoneyDeposited):
        self.balance += event.amount

    @apply
    def withdrawn(self, event: MoneyWithdrawn):
        self.balance -= event.amount
```

## Automatic Selection

When an aggregate has `event_sourced=True`, `domain.repository_for()` automatically returns an event-sourced repository. Initialize the domain first, then ask for repositories inside a domain context:

```python
from protean import current_domain

domain.init(traverse=False)

with domain.domain_context():
    # For standard aggregates → returns standard repository
    repo = current_domain.repository_for(Product)

    # For ES aggregates → returns event-sourced repository
    repo = current_domain.repository_for(Account)
```

No explicit repository definition is needed — the domain handles this automatically.

## Custom ES Repository

For custom query methods, define an explicit event-sourced repository by subclassing `BaseEventSourcedRepository` and registering it:

```python
from protean.core.event_sourced_repository import BaseEventSourcedRepository

class AccountRepository(BaseEventSourcedRepository):
    pass  # Default behavior handles add/get

domain.register(AccountRepository, part_of=Account)
```

**Validation**: The repository factory checks that:
- `part_of` is specified (must be associated with an aggregate)
- The aggregate has `event_sourced=True` (raises `IncorrectUsageError` otherwise)

## How `add()` Works

When you call `repo.add(aggregate)`:

1. **Checks for events**: Only persists if the aggregate has pending events (`aggregate._events`)
2. **Generates fact events** (if enabled): Creates a snapshot event with complete aggregate state
3. **Adds to identity map**: Registers the aggregate in the current UnitOfWork's identity map
4. **Commits**: If no UnitOfWork is in progress, starts and commits one automatically
5. **Events written to event store**: The UnitOfWork commit appends all events to the event store

```python
from protean import UnitOfWork

with domain.domain_context():
    repo = current_domain.repository_for(Account)

    # A command handler runs inside an implicit UnitOfWork, like this block
    with UnitOfWork():
        account = Account.open("ACC-001", "Alice", 1000.0)
        account.deposit(100.0)    # Raises MoneyDeposited event
        repo.add(account)         # Events written to event store on UoW commit
```

## How `get()` Works

When you call `repo.get(identifier)`:

1. **Checks identity map**: If the aggregate was already loaded in the current UnitOfWork, returns it from the identity map (avoids reloading)
2. **Loads from event store**: Calls `event_store.load_aggregate()` which:
   - Checks for a snapshot first (if snapshot threshold is configured)
   - Reads all events (or events after the snapshot) from the stream
   - Replays events through `@apply` methods to reconstruct state
3. **Sets event position**: Records `_event_position` for concurrency tracking
4. **Returns aggregate**: The fully-reconstructed aggregate with current state

```python
with domain.domain_context():
    account = repo.get("ACC-001")
    # Internally: reads events from stream "<domain>::account-ACC-001"
    # Replays: AccountOpened → MoneyDeposited
    assert account.balance == 1100.0
```

If no events exist for the identifier, raises `ObjectNotFoundError`.

## UnitOfWork Integration

Event-sourced repositories integrate with Protean's Unit of Work pattern:

- **Command handlers** run within an implicit UnitOfWork
- Events are accumulated during the handler execution
- All events are persisted atomically on UoW commit
- If the handler raises an exception, no events are persisted

```python
@domain.command(part_of=Account)
class TransferMoney:
    source_id: Identifier(required=True)
    target_id: Identifier(required=True)
    amount: Float(required=True)

@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(TransferMoney)
    def handle_transfer(self, command: TransferMoney):
        repo = current_domain.repository_for(Account)

        # Both operations happen within the same UnitOfWork
        source = repo.get(command.source_id)
        source.withdraw(command.amount)
        repo.add(source)

        target = repo.get(command.target_id)
        target.deposit(command.amount)
        repo.add(target)
        # All events committed together on handler exit
```

## Version Tracking and Concurrency

Each event increments the aggregate's `_version`:

```python
with domain.domain_context():
    account = Account.open("ACC-002", "Bob", 1000.0)  # version: 0
    account.deposit(500.0)   # version: 1
    account.withdraw(200.0)  # version: 2
    assert account._version == 2
```

When persisting, the event store checks the expected version against the stream's actual version. If another process modified the aggregate concurrently, an `ExpectedVersionError` is raised:

```python
# Process A loads account (version 2)
# Process B loads account (version 2)
# Process A deposits and saves → succeeds (version 3)
# Process B deposits and saves → ExpectedVersionError (expected 2, actual 3)
```

This prevents lost updates without pessimistic locking.

## Stream Naming

Events are stored in streams named by the aggregate's stream category and identifier:

```
{domain_name}::{stream_category}-{aggregate_id}
```

Example: `banking::account-ACC-001`

The stream category defaults to the snake_case aggregate name but can be overridden:

```python
@domain.aggregate(event_sourced=True, stream_category="bank_account")
class Account: ...
```
