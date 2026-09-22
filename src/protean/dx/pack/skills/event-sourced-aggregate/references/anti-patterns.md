# Anti-patterns for Event-Sourced Aggregates

Common mistakes when building event-sourced aggregates in Protean and how to avoid them.

## 1. Mutating State Directly in Business Methods

### The Problem

When business methods mutate state directly AND `raise_()` invokes the `@apply` handler, state gets mutated twice — once in the business method and once in `@apply`.

```python
# WRONG — state mutated twice (business method + @apply)
def close(self):
    self.status = "CLOSED"  # First mutation
    self.raise_(AccountClosed(account_id=self.account_id))
    # @apply also sets self.status = "CLOSED" — double mutation!
```

### The Fix

Business methods should only validate preconditions and call `raise_()`. Let `@apply` be the single source of truth for state mutations:

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

## 2. Missing @apply Handler for an Event

### The Problem

If an event type is raised but no `@apply` method is registered for it, Protean raises `IncorrectUsageError` at runtime — both when `raise_()` is called (live path) and when replaying events via `from_events()` or `repo.get()`.

```python
@domain.event(part_of="Order")
class OrderArchived:
    order_id: Identifier(required=True)

# No @apply method for OrderArchived!
# from_events() or repo.get() → IncorrectUsageError
```

### The Fix

Every event type raised by the aggregate must have a corresponding `@apply` method:

```python
@apply
def archived(self, event: OrderArchived):
    self.status = "ARCHIVED"
```

## 3. Forgetting Initial Event in Factory

### The Problem

Creating an aggregate without raising a creation event means the first state change is not recorded.

```python
# WRONG — no creation event
@classmethod
def open(cls, account_id, owner_name):
    return cls(account_id=account_id, owner_name=owner_name)
```

When this aggregate is loaded from the event store, there are no events to replay, so the aggregate would be empty.

### The Fix

Always raise an event in the factory classmethod:

```python
@classmethod
def open(cls, account_id, owner_name):
    account = cls(account_id=account_id, owner_name=owner_name)
    account.raise_(AccountOpened(account_id=account_id, owner_name=owner_name))
    return account
```

## 4. First Event's @apply Not Setting All Required Fields

### The Problem

`from_events()` creates a blank aggregate and applies all events through `@apply`. The first event's `@apply` handler must set ALL fields including identity, otherwise the aggregate will have missing or default values.

```python
# WRONG — @apply handler doesn't set all fields
@apply
def account_opened(self, event: AccountOpened):
    self.account_id = event.account_id
    # Missing: self.owner_name, self.balance
```

### The Fix

Ensure the first event's `@apply` handler establishes ALL aggregate state:

```python
# CORRECT — first event's @apply sets all fields
@apply
def account_opened(self, event: AccountOpened):
    self.account_id = event.account_id
    self.owner_name = event.owner_name
    self.balance = event.balance
    self.status = "ACTIVE"
```

## 5. Using Standard Repository with ES Aggregate

### The Problem

Defining a standard `@domain.repository` for an event-sourced aggregate won't work correctly. ES aggregates require event-sourced repositories.

```python
# WRONG — standard repository for ES aggregate
@domain.repository(part_of=Account)
class AccountRepository:
    ...
```

### The Fix

Either use the auto-selected repository:

```python
repo = current_domain.repository_for(Account)  # Auto-selects ES repo
```

Or define an explicit ES repository by subclassing `BaseEventSourcedRepository`:

```python
from protean.core.event_sourced_repository import BaseEventSourcedRepository

class AccountRepository(BaseEventSourcedRepository):
    pass

domain.register(AccountRepository, part_of=Account)
```

## 6. Overly Large Events

### The Problem

Including too much data in events makes them expensive to store and process:

```python
# WRONG — event carries entire aggregate state
@domain.event(part_of="Order")
class ItemAdded:
    order_id: Identifier(required=True)
    item: Dict()  # Item details
    all_items: List()  # All items (redundant!)
    order_total: Float()  # Calculated (redundant!)
    customer_details: Dict()  # Not related to this change
```

### The Fix

Events should carry only the data relevant to the change:

```python
# CORRECT — event carries only what changed
@domain.event(part_of="Order")
class ItemAdded:
    order_id: Identifier(required=True)
    item_id: Identifier(required=True)
    product_id: String(required=True)
    quantity: Integer(required=True)
    unit_price: Float(required=True)
```

## 7. Forgetting to Raise Events in Business Methods

### The Problem

Mutating state directly without raising events means changes won't be persisted to the event store and won't survive replay:

```python
# WRONG — direct mutation without event
@domain.aggregate(event_sourced=True)
class Account:
    def update_name(self, name):
        self.name = name  # Won't persist — no event raised!
```

### The Fix

ALL state changes must go through `raise_()` and `@apply`:

```python
@domain.aggregate(event_sourced=True)
class Account:
    def update_name(self, name):
        self.raise_(NameUpdated(account_id=self.account_id, name=name))

    @apply
    def name_updated(self, event: NameUpdated):
        self.name = event.name
```

## 8. Not Validating Before Raising Events

### The Problem

Raising events without validation means invalid state changes get recorded:

```python
# WRONG — no validation before raising
def withdraw(self, amount):
    self.raise_(MoneyWithdrawn(account_id=self.account_id, amount=amount))
```

### The Fix

Validate business rules in the business method, before calling `raise_()`:

```python
def withdraw(self, amount):
    if amount <= 0:
        raise ValueError("Amount must be positive")
    if amount > self.balance:
        raise ValueError("Insufficient funds")
    self.raise_(MoneyWithdrawn(account_id=self.account_id, amount=amount))
```

## 9. Querying External State in @apply Methods

### The Problem

`@apply` methods must be pure state mutations — they should not query databases, call APIs, or access other aggregates:

```python
# WRONG — external query in @apply
@apply
def order_placed(self, event: OrderPlaced):
    self.status = "PLACED"
    customer = current_domain.repository_for(Customer).get(event.customer_id)
    self.customer_name = customer.name  # External dependency!
```

### The Fix

Include all needed data in the event itself:

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
