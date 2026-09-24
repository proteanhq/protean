---
name: event-sourced-aggregate
description: "Build event-sourced aggregates in Protean where state is derived by replaying domain events instead of stored as snapshots. Covers the @apply decorator for event application, raising events from business methods, state reconstruction via from_events(), event-sourced repositories, version tracking for optimistic concurrency, and fact events. Use when the user asks to 'create an event-sourced aggregate', 'add event sourcing', 'use event sourcing', 'store events instead of state', 'add an @apply method', 'enable event_sourced', or when they need audit trails, temporal queries, or complete state history for an aggregate."
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
  diagnostic_codes:
    - ES_AGGREGATE_NO_EVENTS
    - ES_EVENT_MISSING_APPLY
---

# Event-Sourced Aggregate

## Basic structure

An event-sourced aggregate stores events instead of current state. State is reconstructed by replaying events through `@apply` methods. Business methods validate and call `raise_()`, which automatically invokes the matching `@apply` handler to mutate state:

```python
from protean import Domain
from protean.core.aggregate import apply
from protean.fields import String, Identifier

domain = Domain()

@domain.event(part_of="Account")
class AccountOpened:
    account_id: Identifier(required=True)
    owner_name: String(required=True)

@domain.event(part_of="Account")
class AccountClosed:
    account_id: Identifier(required=True)

@domain.aggregate(event_sourced=True)
class Account:
    account_id: Identifier(identifier=True)
    owner_name: String(required=True)
    status: String(default="ACTIVE")

    @classmethod
    def open(cls, account_id, owner_name):
        account = cls(account_id=account_id, owner_name=owner_name)
        account.raise_(AccountOpened(
            account_id=account_id, owner_name=owner_name
        ))
        return account

    def close(self):
        if self.status != "ACTIVE":
            raise ValueError("Account is not active")
        self.raise_(AccountClosed(account_id=self.account_id))

    @apply
    def opened(self, event: AccountOpened):
        self.status = "ACTIVE"

    @apply
    def closed(self, event: AccountClosed):
        self.status = "CLOSED"
```

## Key rules

1. **Enable with `event_sourced=True`** — Pass to the `@domain.aggregate` decorator
2. **`@apply` is the single source of truth for state mutations** — `raise_()` automatically invokes the matching `@apply` handler to mutate state. Business methods should validate preconditions and call `raise_()` — never mutate state directly
3. **Every event must have a corresponding `@apply` handler** — When `raise_()` is called, it looks up and invokes the `@apply` handler for that event type. A missing handler raises `IncorrectUsageError`
4. **`@apply` runs on both live and replay paths** — The same `@apply` handler runs when `raise_()` is called during normal operations AND when replaying events from the event store. This guarantees identical state regardless of path
5. **Each `@apply` method handles exactly one event type** — Use a type annotation on the event parameter: `def opened(self, event: AccountOpened)`
6. **Use factory classmethods for creation** — Create instance, raise initial event, return instance. This ensures the creation event is always the first event in the aggregate's stream
7. **Import `apply` from `protean.core.aggregate`** — `from protean import apply` also works and is the same decorator; this skill uses the `protean.core.aggregate` path throughout
8. **Events must be registered with `part_of`** — Associate each event with its aggregate: `@domain.event(part_of="Account")`
9. **Version auto-increments with each event** — Each raised domain event increments `_version`, which drives optimistic concurrency control. Fact-event snapshots (rule 11) do not increment `_version`
10. **ES repository is selected automatically** — `domain.repository_for(Account)` returns an event-sourced repository when the aggregate has `event_sourced=True`
11. **Fact events auto-generate state snapshots** — Use `@domain.aggregate(event_sourced=True, fact_events=True)` to auto-publish complete state after each persist
12. **First event's `@apply` must set ALL fields** — `from_events()` creates a blank aggregate and applies all events through `@apply`, so the first event's handler must establish all state including identity

## The @apply pattern

Business methods validate preconditions and call `raise_()`. The `@apply` handler performs the actual state mutation — this is the single source of truth for state changes:

```python
# 1. Business method — validates then raises (NO direct state mutation)
def close(self):
    if self.status != "ACTIVE":
        raise ValueError("Account is not active")
    self.raise_(AccountClosed(account_id=self.account_id))

# 2. @apply method — mutates state (called automatically by raise_())
@apply
def closed(self, event: AccountClosed):
    self.status = "CLOSED"
```

When `close()` is called:
1. The business method validates preconditions
2. `raise_()` increments `_version`, appends the event, then invokes the `@apply` handler (wrapped in invariant checks)
3. The `@apply` handler mutates state (`self.status = "CLOSED"`)
4. The event is persisted to the event store when the repository saves

When the aggregate is loaded later (via `from_events()` or `repo.get()`):
1. All events are read from the event store
2. Each event is replayed through its `@apply` method
3. The aggregate arrives at its current state

Because `@apply` runs in both paths, live and replay always produce identical state.

## Factory classmethod pattern

Always use a factory classmethod to create new event-sourced aggregates:

```python
@classmethod
def register(cls, user_id, name, email):
    user = cls(user_id=user_id, name=name, email=email)
    user.raise_(UserRegistered(user_id=user_id, name=name, email=email))
    return user

# Usage
user = User.register(user_id="U-001", name="Alice", email="alice@example.com")
```

This ensures the creation event is always the first event in the aggregate's stream.

### Alternative: `_create_new()` for lean creation

When not all required fields can be satisfied at construction time, use `_create_new()` — it creates a blank aggregate with only identity, and lets the creation event's `@apply` handler establish all state:

```python
@classmethod
def register(cls, user_id, name, email):
    user = cls._create_new(user_id=user_id)  # Only identity required
    user.raise_(UserRegistered(user_id=user_id, name=name, email=email))
    return user
```

With `_create_new()`, the `@apply` handler for `UserRegistered` must set ALL fields. This is the preferred pattern when the aggregate has many required fields.

## State reconstruction

Event-sourced aggregates can be reconstructed from their event history:

```python
# Build aggregate from events
user = User.from_events(events)

# Internally:
# 1. Creates a blank aggregate via _create_for_reconstitution()
# 2. Applies ALL events sequentially through their @apply methods
# 3. The first event's @apply handler must set ALL fields including identity
```

The repository handles this automatically when loading:
```python
repo = domain.repository_for(User)
user = repo.get(user_id)  # Reconstructs from event store
```

## Event-sourced repository

ES aggregates use a specialized repository that persists events instead of state:

```python
from protean.utils.globals import current_domain

# The domain auto-selects the right repository type
repo = current_domain.repository_for(Account)

# Persist — writes events to event store
repo.add(account)

# Load — reconstructs from event stream
account = repo.get(account_id)
```

For custom queries, define an explicit ES repository by subclassing `BaseEventSourcedRepository` and registering it against the aggregate:
```python
from protean.core.event_sourced_repository import BaseEventSourcedRepository

class AccountRepository(BaseEventSourcedRepository):
    pass  # Default behavior handles add/get

domain.register(AccountRepository, part_of=Account)
```

See [Event-Sourced Repository](references/event-sourced-repository.md) for details.

## Fact events

Enable fact events to auto-generate state snapshots after each persist:

```python
@domain.aggregate(event_sourced=True, fact_events=True)
class Product:
    name: String(required=True)
    price: Float(required=True)
    ...
```

Each time the aggregate is saved, Protean auto-generates a `ProductFactEvent` containing the complete state. Downstream consumers can subscribe to these instead of tracking individual delta events.

Use fact events when:
- External systems need complete state snapshots
- Migrating from traditional to event-sourced architecture
- Building projections that need full state rather than deltas

See [Snapshots and Fact Events](references/snapshots-and-fact-events.md) for details.

## When event sourcing fits

Choose event sourcing when an aggregate meets **2 or more** of these criteria:

| Criterion | Indicator |
|-----------|-----------|
| **Audit trail** | Regulatory compliance, financial transactions, complete traceability |
| **Temporal queries** | "What was the state at time T?", historical reporting |
| **Complex state transitions** | Multi-step workflows, intricate business rules |
| **Event-driven integration** | Other bounded contexts consume events as primary data |
| **Team readiness** | Team understands event modeling and can operate event stores |

You can mix patterns per-aggregate within the same domain:
```python
@domain.aggregate                              # Standard — state stored directly
class Product: ...

@domain.aggregate(event_sourced=True)       # Event sourced — state from events
class Order: ...
```

## Common mistakes

### Mutating state directly in business methods

```python
# WRONG — state mutated in business method AND in @apply (double mutation)
def close(self):
    self.status = "CLOSED"  # Don't do this
    self.raise_(AccountClosed(account_id=self.account_id))

@apply
def closed(self, event: AccountClosed):
    self.status = "CLOSED"  # This also runs via raise_()!
```

Business methods should only validate and call `raise_()`. Let `@apply` handle all state mutations:

```python
# CORRECT — validate then raise, @apply handles state
def close(self):
    if self.status != "ACTIVE":
        raise ValueError("Account is not active")
    self.raise_(AccountClosed(account_id=self.account_id))

@apply
def closed(self, event: AccountClosed):
    self.status = "CLOSED"  # Single source of truth
```

### Missing @apply handler for an event

Every event type raised by the aggregate must have a corresponding `@apply` method. Missing one raises `IncorrectUsageError` at runtime (`No @apply handler registered for event ...`) because `raise_()` invokes `@apply` automatically. `check` reports this ahead of time as `ES_EVENT_MISSING_APPLY`.

### Event-sourced aggregate with no events

An `event_sourced=True` aggregate that raises no domain events has no state history and cannot be rebuilt by replay. `check` reports this as `ES_AGGREGATE_NO_EVENTS`: declare at least one event with `part_of=<Aggregate>` and raise it from the aggregate's behaviour, or drop `event_sourced=True` if the aggregate is not meant to be event-sourced.

### Forgetting to raise initial event in factory

```python
# WRONG — no creation event recorded
@classmethod
def open(cls, account_id, owner_name):
    return cls(account_id=account_id, owner_name=owner_name)
```

Always `raise_()` an event in the factory classmethod.

### Using standard repository with ES aggregate

`repository_for()` returns the event-sourced repository automatically for an ES aggregate. For custom query methods, subclass `BaseEventSourcedRepository` and register it. A standard `@domain.repository` builds a state-based repository, which is the wrong persistence model for an ES aggregate.

See [Anti-patterns](references/anti-patterns.md) for more.

## Detailed references

### Core Concepts
- [The @apply Decorator](references/apply-decorator.md) - Mechanics, validation rules, projection maps
- [Event-Sourced Repository](references/event-sourced-repository.md) - Persistence, loading, UnitOfWork integration
- [Snapshots and Fact Events](references/snapshots-and-fact-events.md) - Performance optimization, state snapshots
- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

### Complete Examples
- [Basic ES Aggregate](assets/es_aggregate_basic.py) - User lifecycle with registration, activation, deactivation
- [ES Aggregate with Entities](assets/es_aggregate_with_entities.py) - Order with line items and value objects
- [ES Aggregate Command Flow](assets/es_aggregate_command_flow.py) - Full command → handler → aggregate → event flow
- [ES Aggregate with Fact Events](assets/es_aggregate_fact_events.py) - Auto-generated state snapshots and mixed patterns

### Related Skills
- `aggregate` - Base aggregate structure, fields, invariants, associations
- `event` - Event definition, naming conventions, event fields
- `event-handler` - Event handler structure, @handle decorator
- `command-handler` - Command handler processing
- `repository` - Standard repository (contrast with ES repository)

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
