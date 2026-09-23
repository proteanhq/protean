---
name: application-service
description: Define a Protean application service - a stateless orchestration layer that coordinates use cases between external callers (API controllers, CLI handlers, background jobs) and the domain model. Application services load aggregates, invoke domain methods, and persist results without containing business logic themselves. They are always associated with one aggregate via part_of and use the @use_case decorator for automatic UnitOfWork wrapping. Unlike command handlers, application services are invoked directly (not via domain.process()) and always return values synchronously. Use when you need to define a use case, orchestrate a domain operation, create an application service, implement a use-case method, add an entry point for domain operations, wire an API to domain logic in pure DDD (non-CQRS), or when the user asks to "create an application service", "add a use case", "implement an application service", "orchestrate domain operations". Application services are the DDD approach; for CQRS use command handlers instead.
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
---

# Application Service

## Basic structure

```python
from protean import Domain, current_domain, use_case
from protean.fields import Identifier, String

domain = Domain()

@domain.aggregate
class User:
    email: String()
    name: String()
    status: String(default="INACTIVE")

    def activate(self):
        self.status = "ACTIVE"

@domain.application_service(part_of=User)
class UserApplicationServices:
    @use_case
    def register_user(self, email: str, name: str) -> Identifier:
        user = User(email=email, name=name)
        current_domain.repository_for(User).add(user)
        return user.id

    @use_case
    def activate_user(self, user_id: Identifier) -> None:
        user = current_domain.repository_for(User).get(user_id)
        user.activate()
        current_domain.repository_for(User).add(user)
```

## Key rules

1. **part_of is required** — Every application service must be associated with exactly one aggregate: `@domain.application_service(part_of=User)`. If the service is defined in the same file as the aggregate, use a string reference (`part_of="User"`) to avoid circular dependencies
2. **Use @use_case decorator** — Mark each use case method with `@use_case` to get automatic UnitOfWork wrapping. Import from `protean`: `from protean import use_case`
3. **Implicit UnitOfWork** — Each `@use_case` method runs within a UnitOfWork automatically. On success, changes are committed; on exception, everything is rolled back
4. **Direct invocation** — Instantiate and call directly: `svc = UserServices(); svc.register_user(...)`. NOT dispatched via `domain.process()`
5. **Synchronous return values** — Application services always execute synchronously and return values to the caller immediately
6. **Thin orchestration only** — Load aggregate, call domain method, persist result. No business logic in the service; push decisions into aggregates or domain services
7. **One use case per method** — Each method represents a single, cohesive business operation
8. **Persist one aggregate** — A use case method should persist only one aggregate. Use domain events for cross-aggregate consistency
9. **Use case naming** — Name methods after business operations: `register_user`, `place_order`, `cancel_subscription`
10. **No handle_error hook** — Unlike command/event handlers, exceptions propagate directly to the caller. The UnitOfWork rolls back, then the exception re-raises

## Application service options

| Option | Purpose | Required | Default |
|--------|---------|----------|---------|
| `part_of` | Associate service with an aggregate class | Yes | None |

## Quick example: Multiple use cases

```python
@domain.application_service(part_of=Account)
class AccountServices:
    @use_case
    def create_account(self, email: str) -> Identifier:
        account = Account(email=email)
        current_domain.repository_for(Account).add(account)
        return account.id

    @use_case
    def activate_account(self, account_id: Identifier) -> None:
        account = current_domain.repository_for(Account).get(account_id)
        account.activate()
        current_domain.repository_for(Account).add(account)

    @use_case
    def deactivate_account(self, account_id: Identifier) -> None:
        account = current_domain.repository_for(Account).get(account_id)
        account.deactivate()
        current_domain.repository_for(Account).add(account)
```

## Invocation pattern

```python
# Direct instantiation and call (NOT domain.process())
svc = AccountServices()
account_id = svc.create_account(email="user@example.com")
svc.activate_account(account_id=account_id)
```

## The @use_case decorator

The `@use_case` decorator has two responsibilities:

1. **UnitOfWork wrapping** — The method body executes inside a `UnitOfWork` context. Commits on success, rolls back on exception.
2. **Execution logging** — Logs invocation at INFO level for traceability.

Only `@use_case`-decorated methods get UoW treatment. Regular helper methods do not:

```python
@domain.application_service(part_of=Order)
class OrderServices:
    @use_case
    def place_order(self, items: list) -> Identifier:
        # Runs inside UnitOfWork
        order = Order.create(items=items)
        current_domain.repository_for(Order).add(order)
        return order.id

    def _validate_items(self, items):
        # Regular helper - NO UnitOfWork wrapping
        ...
```

## Error handling

Exceptions propagate directly to the caller. The UnitOfWork auto-rolls back:

```python
try:
    svc = UserServices()
    user_id = svc.register_user(email="john@example.com", name="John")
except ValidationError as exc:
    # Handle validation errors (e.g., return 400)
    ...
except Exception as exc:
    # Handle unexpected errors (e.g., return 500)
    ...
```

## Application services vs. command handlers

| Aspect | Application Service | Command Handler |
|--------|-------------------|-----------------|
| Invocation | Direct: `svc.method()` | Via dispatch: `domain.process(cmd)` |
| Return values | Always synchronous | Depends on sync/async mode |
| Error handling | Exceptions propagate to caller | `handle_error` hook available |
| Architecture | Pure DDD | CQRS |
| Input | Plain Python arguments | Command DTO |

When evolving to CQRS, application services are replaced by commands + command handlers.

## Common mistakes

### Missing part_of

```python
@domain.application_service  # Wrong! Missing part_of
class UserServices:
    pass
```

Instead: Always specify part_of with the aggregate class

```python
@domain.application_service(part_of=User)  # Correct!
class UserServices:
    pass
```

### Putting business logic in the service

```python
@use_case
def place_order(self, items: list) -> Identifier:
    if len(items) == 0:
        raise ValidationError("Order must have items")  # Wrong!
    total = sum(i.price * i.quantity for i in items)  # Wrong!
    order = Order(items=items, total=total)
    ...
```

Instead: Push business logic into the aggregate

```python
@use_case
def place_order(self, items: list) -> Identifier:
    order = Order.place(items=items)  # Aggregate enforces rules
    current_domain.repository_for(Order).add(order)
    return order.id
```

### Using domain.process() instead of direct invocation

```python
# Wrong! Application services are not dispatched via domain.process()
domain.process(some_service_call)
```

Instead: Instantiate and call directly

```python
svc = OrderServices()
order_id = svc.place_order(items=[...])
```

### Wrapping in UnitOfWork manually

```python
@use_case
def register_user(self, email, name):
    with UnitOfWork():  # Unnecessary! Already implicit via @use_case
        user = User(email=email, name=name)
        ...
```

Instead: Let `@use_case` handle the UnitOfWork

```python
@use_case
def register_user(self, email, name):
    user = User(email=email, name=name)
    current_domain.repository_for(User).add(user)
    return user.id
```

### Persisting multiple aggregates

```python
@use_case
def transfer_funds(self, from_id, to_id, amount):
    from_acct = current_domain.repository_for(Account).get(from_id)
    to_acct = current_domain.repository_for(Account).get(to_id)
    from_acct.debit(amount)
    to_acct.credit(amount)
    current_domain.repository_for(Account).add(from_acct)
    current_domain.repository_for(Account).add(to_acct)  # Wrong!
```

Instead: Persist one aggregate and use events for cross-aggregate sync

## Detailed references

### Core concepts
- [The @use_case Decorator](references/use-case-decorator.md) - How UnitOfWork wrapping and logging work
- [Unit of Work](references/unit-of-work.md) - Transaction semantics in application services
- [Return Values](references/return-values.md) - Patterns for returning data from use cases
- [Error Handling](references/error-handling.md) - Exception propagation and UoW rollback
- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

### Complete examples
- [Simple Service](assets/application_service_simple.py) - Basic service with one use case
- [Multiple Use Cases](assets/application_service_multiple_use_cases.py) - Service with multiple @use_case methods
- [With Events](assets/application_service_with_events.py) - Aggregate raises events during service operations
- [Return Values](assets/application_service_return_values.py) - Patterns for synchronous return values
- [Error Handling](assets/application_service_error_handling.py) - Exception propagation and rollback

### Related skills
- `aggregate` - Application services orchestrate aggregates
- `command-handler` - CQRS alternative; replaces application services when evolving to CQRS
- `event` - Aggregates may raise events during application service operations
- `repository` - Application services use repositories to load/persist aggregates
- `domain-service` - Cross-aggregate logic invoked from application services

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
