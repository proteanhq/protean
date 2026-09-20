# The @apply Decorator

The `@apply` decorator is the core mechanism that connects events to state changes in event-sourced aggregates.

## Import

```python
from protean.core.aggregate import apply
```

**Important**: Import from `protean.core.aggregate`, not from `protean` directly.

## How It Works

### Method Signature

Each `@apply` method must:
1. Accept exactly **two** parameters: `self` and the event
2. The event parameter must have a **type annotation** with an Event class

```python
@apply
def activated(self, event: UserActivated):
    self.status = "ACTIVE"
```

### Validation

The decorator validates at class definition time:
- **Too many arguments**: Raises `IncorrectUsageError` if more than 2 parameters (self + event)
- **Missing annotation**: Raises `IncorrectUsageError` if the event parameter is not type-annotated
- **Wrong type**: Raises `IncorrectUsageError` if the annotation is not an Event class (e.g., a Command)
- **Missing argument**: Raises `IncorrectUsageError` if no event parameter is provided

```python
# WRONG — too many arguments
@apply
def activated(self, event: UserActivated, extra: str):  # IncorrectUsageError
    ...

# WRONG — missing type annotation
@apply
def activated(self, event):  # IncorrectUsageError
    ...

# WRONG — annotated with a Command, not an Event
@apply
def activated(self, command: ActivateUser):  # IncorrectUsageError
    ...
```

## Projection Maps

During domain initialization, Protean scans all `@apply` methods and builds two class-level maps:

1. **`_projections`**: Maps event fully-qualified name (FQN) to the set of `@apply` methods that handle it
2. **`_events_cls_map`**: Maps event FQN to the Event class itself

These maps are used during event replay to find the correct handler for each event.

```python
# After domain.init(), the aggregate class has:
User._projections[fqn(UserActivated)]  # → {User.activated}
User._events_cls_map[fqn(UserActivated)]  # → UserActivated
```

## Event Application Flow

### When raising events (live path)

`raise_()` automatically invokes the matching `@apply` handler. Business methods should validate and call `raise_()` — never mutate state directly:

```
# In business method:
self.raise_(event)
  → appends event to aggregate._events
  → invokes matching @apply handler (wrapped in invariant checks via atomic_change)
  → @apply handler mutates state
  → increments aggregate._version
```

### When replaying events (loading from event store)

The same `@apply` methods run during replay via `from_events()` or `repo.get()`:

```
User.from_events(event_list)
  → creates blank aggregate via cls._create_for_reconstitution()
  → for each event: calls aggregate._apply(event)
    → looks up _projections for event FQN
    → calls matching @apply method(s)
    → method mutates aggregate state
    → increments _version
```

Because the same `@apply` handler runs in both paths, live processing and replay always produce identical state.

## Missing Handler Error

If an event is applied but no `@apply` method is registered for it, a `NotImplementedError` is raised:

```python
# If User has no @apply method for UserArchived:
user._apply(UserArchived(user_id="U-001"))
# → NotImplementedError: No handler registered for event `...UserArchived` in `User`
```

This ensures every event type has explicit handling logic.

## Naming Conventions

`@apply` method names should describe the state that results from the event:

| Event | @apply Method Name |
|-------|-------------------|
| `UserRegistered` | `registered` |
| `UserActivated` | `activated` |
| `OrderPlaced` | `placed` or `order_placed` |
| `MoneyDeposited` | `money_deposited` |

The method name is purely for readability — the decorator uses the type annotation to determine which event it handles.

## Using `_` for Unused Event Parameter

When the `@apply` method doesn't need data from the event, use `_` as the parameter name:

```python
@apply
def activated(self, _: UserActivated):
    self.status = "ACTIVE"  # No event data needed
```

This signals that the method doesn't use the event payload, only the event type matters.
