# Cross-Aggregate Projector

A cross-aggregate projector listens to events from more than one aggregate and combines them into one projection. Use it for a read model that needs data from several write models, such as a user's balance built from `User` registrations and `Transaction` events. The SKILL.md "Cross-aggregate projector" example shows the full `TransactionProjector`.

## The aggregates, events, and projection

The examples on this page use two aggregates:

```python
from protean.core.projector import on

@domain.aggregate
class User:
    email: String()
    name: String()

@domain.aggregate
class Transaction:
    user_id: Identifier()
    amount: Float()
```

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

The projection combines data from both aggregates:

```python
@domain.projection
class Balances:
    user_id: Identifier(identifier=True)
    name: String()
    balance: Float()
```

## Specifying multiple aggregates

### Using aggregates parameter

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

Protean derives a stream category from each aggregate: `User.meta_.stream_category` and `Transaction.meta_.stream_category`.

### Using stream_categories parameter

Pass `stream_categories` instead of `aggregates`, as in the SKILL.md `SystemMetricsProjector` example, when:
- You don't have direct access to the aggregate class
- You want to use custom stream category names
- You're listening to streams from external bounded contexts

A stream category is domain-qualified: `<domain>::<aggregate>`. A bare name like `"user"` never matches. Derive the category from the registered aggregate with `meta_.stream_category`, or write it in full, as in `"shop::user"` for a domain named `shop`.

## Event ordering considerations

Events from different aggregates can arrive in any order, so a `Transacted` event can reach the projector before the user's `Registered` event. Write each handler so it copes with a missing projection record:

```python
from protean.exceptions import ObjectNotFoundError


@on(Transacted)
def on_transacted(self, event: Transacted):
    repo = domain.repository_for(Balances)
    try:
        balance = repo.get(event.user_id)
        balance.balance += event.amount
    except ObjectNotFoundError:
        # User registration event hasn't arrived yet
        balance = Balances(user_id=event.user_id, name="", balance=event.amount)
    repo.add(balance)
```

With this handler, `on_registered` must set the name on the record when it already exists and keep its balance. Adding a new `Balances` for a `user_id` that is already stored raises `ValidationError` ("Balances with user_id '...' is already present").

## Complete example

See [projector_cross_aggregate.py](../assets/projector_cross_aggregate.py) for a complete, runnable example.

## Related

- [Single-Aggregate Projector](single-aggregate.md): Simpler pattern with one aggregate
- [Multiple Projectors](multiple-projectors.md): Multiple projectors for different views
- [Anti-patterns](anti-patterns.md): Common mistakes to avoid
- `event-handler`: Event handlers for cross-aggregate coordination (compare/contrast)
