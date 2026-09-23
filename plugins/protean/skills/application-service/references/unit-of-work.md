# Unit of Work in Application Services

Use case methods always execute within a `UnitOfWork` context. The UnitOfWork pattern ensures that all changes to an aggregate cluster are treated as a single, atomic transaction.

## Automatic Wrapping

The `@use_case` decorator wraps every method invocation in a UnitOfWork. You do NOT need to specify it explicitly:

```python
@domain.application_service(part_of=User)
class UserServices:
    @use_case
    def register_user(self, email: str, name: str) -> Identifier:
        # Implicitly inside UnitOfWork
        user = User(email=email, name=name)
        current_domain.repository_for(User).add(user)
        return user.id
```

This is equivalent to:

```python
@use_case
def register_user(self, email: str, name: str) -> Identifier:
    with UnitOfWork():
        user = User(email=email, name=name)
        current_domain.repository_for(User).add(user)
        return user.id
```

Do NOT manually wrap — it is redundant and unnecessary.

## Transaction Semantics

### On Success
When a `@use_case` method completes without exception:
1. All aggregate mutations are persisted
2. All domain events raised by aggregates are published
3. The UnitOfWork commits

### On Failure
When an exception is raised inside a `@use_case` method:
1. All pending changes are rolled back
2. No partial state is persisted
3. The exception propagates to the caller

## Scope

A `UnitOfWork` context applies to objects within one aggregate cluster, not across multiple aggregates:

```python
@use_case
def transfer_funds(self, from_id, to_id, amount):
    # Load both accounts
    from_acct = current_domain.repository_for(Account).get(from_id)
    to_acct = current_domain.repository_for(Account).get(to_id)

    # Mutate both
    from_acct.debit(amount)
    to_acct.credit(amount)

    # Should persist only one — use events for the other
    current_domain.repository_for(Account).add(from_acct)
    # to_acct should be synced via domain events
```

## Best Practices

1. **One aggregate per UoW**: Persist only one aggregate root per use case method
2. **Don't nest UoWs**: The `@use_case` decorator already provides one
3. **Let exceptions propagate**: The UoW handles rollback automatically
4. **Use events for cross-aggregate consistency**: Raise events from the aggregate, handle them in event handlers

See [With Events](../assets/application_service_with_events.py) for a complete example showing events within UoW.
