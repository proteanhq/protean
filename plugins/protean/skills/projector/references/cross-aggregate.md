# Cross-Aggregate Projector

## Overview

A cross-aggregate projector listens to events from multiple aggregates and combines them into a single projection. This is essential for building denormalized views that span aggregate boundaries - a core CQRS pattern where the read model needs data from multiple write models.

## When to use

- Building a dashboard view that combines data from multiple aggregates
- Creating a reporting projection that aggregates metrics across bounded contexts
- Maintaining a user balance view that tracks both registration (User) and transactions (Transaction)
- Any read model that requires data from more than one aggregate's event stream

## Specifying multiple aggregates

### Using aggregates parameter

The most common way to listen to multiple aggregates:

```python
@domain.projector(
    projector_for=Balances,
    aggregates=[User, Transaction],
)
class TransactionProjector:
    @on(Registered)
    def on_registered(self, event: Registered):
        # Handle User aggregate events
        ...

    @on(Transacted)
    def on_transacted(self, event: Transacted):
        # Handle Transaction aggregate events
        ...
```

Protean derives stream categories from each aggregate automatically: `User.meta_.stream_category` and `Transaction.meta_.stream_category`.

### Using stream_categories parameter

For finer control, specify stream categories directly:

```python
@domain.projector(
    projector_for=SystemMetrics,
    stream_categories=["user", "order", "payment"],
)
class SystemMetricsProjector:
    ...
```

This is useful when:
- You don't have direct access to the aggregate class
- You want to use custom stream category names
- You're listening to streams from external bounded contexts

## Code walkthrough

### Events from different aggregates

Each event belongs to its own aggregate via `part_of`:

```python
@domain.event(part_of="User")
class Registered:
    user_id: Identifier()
    email: String()
    name: String()

@domain.event(part_of="Transaction")
class Transacted:
    user_id: Identifier()
    amount: Float()
```

### Cross-aggregate projection

The projection combines data from both aggregates:

```python
@domain.projection
class Balances:
    user_id: Identifier(identifier=True)
    name: String()
    balance: Float()
```

### The cross-aggregate projector

The projector handles events from both aggregates, each updating the shared projection:

```python
@domain.projector(
    projector_for=Balances,
    aggregates=[User, Transaction],
)
class TransactionProjector:
    @on(Registered)
    def on_registered(self, event: Registered):
        balance = Balances(user_id=event.user_id, name=event.name, balance=0)
        domain.repository_for(Balances).add(balance)

    @on(Transacted)
    def on_transacted(self, event: Transacted):
        balance = domain.repository_for(Balances).get(event.user_id)
        balance.balance += event.amount
        domain.repository_for(Balances).add(balance)
```

## Event ordering considerations

When combining events from multiple aggregates, be aware that:
- Events from different aggregates may arrive in any order
- The Registered event may arrive after a Transacted event
- Design handler methods to handle missing projection records gracefully

```python
@on(Transacted)
def on_transacted(self, event: Transacted):
    repo = domain.repository_for(Balances)
    try:
        balance = repo.get(event.user_id)
        balance.balance += event.amount
    except NotFoundError:
        # User registration event hasn't arrived yet
        balance = Balances(user_id=event.user_id, name="", balance=event.amount)
    repo.add(balance)
```

## Complete example

See [projector_cross_aggregate.py](../assets/projector_cross_aggregate.py) for a complete, runnable example.

## Related

- [Single-Aggregate Projector](single-aggregate.md) - Simpler pattern with one aggregate
- [Multiple Projectors](multiple-projectors.md) - Multiple projectors for different views
- [Anti-patterns](anti-patterns.md) - Common mistakes to avoid
- `event-handler` - Event handlers for cross-aggregate coordination (compare/contrast)
