# Anti-patterns for Event-Sourced Aggregates

The examples on this page use these events and aggregates:

```python
from protean.core.aggregate import apply
from protean.fields import Decimal, Identifier, String
from protean.utils.globals import current_domain

@domain.event(part_of="Account")
class AccountOpened:
    account_id: Identifier(required=True)
    owner_name: String(required=True)
    balance: Decimal(precision=19, scale=4, required=True)

@domain.event(part_of="Account")
class NameUpdated:
    account_id: Identifier(required=True)
    name: String(required=True)

@domain.aggregate(event_sourced=True)
class Account:
    account_id: Identifier(identifier=True)
    owner_name: String(required=True)
    balance: Decimal(precision=19, scale=4, default=0)
    status: String(default="ACTIVE")

    @apply
    def account_opened(self, event: AccountOpened):
        self.account_id = event.account_id
        self.owner_name = event.owner_name
        self.balance = event.balance
        self.status = "ACTIVE"

@domain.aggregate(event_sourced=True)
class Order:
    order_id: Identifier(identifier=True)
    status: String()
    customer_name: String()
```

## 1. Missing @apply Handler for an Event

### The Problem

The `IncorrectUsageError` for a missing `@apply` method is raised on both paths: when `raise_()` is called, and when events are replayed through `from_events()` or `repo.get()`.

```python
@domain.event(part_of="Order")
class OrderArchived:
    order_id: Identifier(required=True)

# No @apply method for OrderArchived!
# from_events() or repo.get() → IncorrectUsageError
```

### The Fix

```python
@apply
def archived(self, event: OrderArchived):
    self.status = "ARCHIVED"
```

## 2. Forgetting Initial Event in Factory

### The Problem

```python
# fragment
# WRONG: no creation event
@classmethod
def open(cls, account_id, owner_name):
    return cls(account_id=account_id, owner_name=owner_name)
```

With no events raised, the event-sourced repository's `add()` persists nothing (it no-ops when the aggregate has no events). A later `repo.get()` then raises `ObjectNotFoundError` because the stream is empty.

### The Fix

```python
@classmethod
def open(cls, account_id, owner_name):
    account = cls(account_id=account_id, owner_name=owner_name)
    account.raise_(AccountOpened(account_id=account_id, owner_name=owner_name))
    return account
```

## 3. First Event's @apply Not Setting All Required Fields

### The Problem

`from_events()` creates a blank aggregate by setting every field to `None` directly, bypassing declared field defaults, then applies all events through `@apply`. The first event's `@apply` handler must set ALL fields including identity: any field it leaves unset stays `None`, never its declared default.

```python
# fragment
# WRONG: @apply handler doesn't set all fields
@apply
def account_opened(self, event: AccountOpened):
    self.account_id = event.account_id
    # Missing: self.owner_name, self.balance
```

### The Fix

Set every field in the first event's handler, as `account_opened` does in the `Account` class at the top of this page.

## 4. Using Standard Repository with ES Aggregate

### The Problem

A standard `@domain.repository` registered for an event-sourced aggregate raises no error. `repository_for(Account)` still returns an event-sourced repository that the domain builds on its own, so the methods defined on the standard class are missing from the object you get back.

```python
# fragment
# WRONG: standard repository for ES aggregate
@domain.repository(part_of=Account)
class AccountRepository:
    ...
```

### The Fix

Use the repository `repository_for()` returns, or subclass `BaseEventSourcedRepository` and register it with `domain.register(AccountRepository, part_of=Account)`, as the skill's "Event-sourced repository" section shows.

## 5. Overly Large Events

### The Problem

An event that carries data unrelated to the change is expensive to store and process:

```python
# fragment
# WRONG: event carries entire aggregate state
@domain.event(part_of="Order")
class ItemAdded:
    order_id: Identifier(required=True)
    item: Dict()  # Item details
    all_items: List()  # All items (redundant!)
    order_total: Decimal(precision=19, scale=4)  # Calculated (redundant!)
    customer_details: Dict()  # Not related to this change
```

### The Fix

```python
# CORRECT: event carries only what changed
@domain.event(part_of="Order")
class ItemAdded:
    order_id: Identifier(required=True)
    item_id: Identifier(required=True)
    product_id: String(required=True)
    quantity: Integer(required=True)
    unit_price: Decimal(precision=19, scale=4, required=True)
```

## 6. Forgetting to Raise Events in Business Methods

### The Problem

A direct assignment changes the aggregate in memory only. With no event raised, `repo.add()` writes nothing, and the change is gone on the next load:

```python
# fragment
# WRONG: direct mutation without event
@domain.aggregate(event_sourced=True)
class Account:
    def update_name(self, name):
        self.name = name  # Won't persist: no event raised!
```

### The Fix

```python
@domain.aggregate(event_sourced=True)
class Account:
    account_id: Identifier(identifier=True)
    name: String()

    def update_name(self, name):
        self.raise_(NameUpdated(account_id=self.account_id, name=name))

    @apply
    def name_updated(self, event: NameUpdated):
        self.name = event.name
```

## 7. Querying External State in @apply Methods

### The Problem

An `@apply` method runs again on every replay, so it must only set state from the event. A query to a database, an API or another aggregate can return a different answer on replay:

```python
# fragment
# WRONG: external query in @apply
@apply
def order_placed(self, event: OrderPlaced):
    self.status = "PLACED"
    customer = current_domain.repository_for(Customer).get(event.customer_id)
    self.customer_name = customer.name  # External dependency!
```

### The Fix

Put the data the handler needs in the event:

```python
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: String(required=True)
    customer_name: String(required=True)  # Include needed data

@apply
def order_placed(self, event: OrderPlaced):
    self.status = "PLACED"
    self.customer_name = event.customer_name
```
