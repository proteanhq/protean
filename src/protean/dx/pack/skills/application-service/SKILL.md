---
name: application-service
description: Define a Protean application service - a stateless orchestration layer that coordinates use cases between external callers (API controllers, CLI handlers, background jobs) and the domain model. Application services load aggregates, invoke domain methods, and persist results without containing business logic. They are always associated with one aggregate via part_of and use the @use_case decorator for automatic UnitOfWork wrapping. Unlike command handlers, application services are invoked directly (not via domain.process()) and return values synchronously. Use when you need to define a use case, orchestrate a domain operation, create an application service, implement a use-case method, add an entry point for domain operations, wire an API to domain logic in pure DDD (non-CQRS), or when the user asks to "create an application service", "add a use case", "implement an application service", "orchestrate domain operations". Application services are the DDD approach; for CQRS use command handlers instead.
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
    email: String(required=True)
    name: String()
    status: String(default="INACTIVE")

    def activate(self):
        self.status = "ACTIVE"

@domain.application_service(part_of=User)
class UserServices:
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

1. **part_of is required**: Every application service must be associated with exactly one aggregate: `@domain.application_service(part_of=User)`. If the service is defined in the same file as the aggregate, use a string reference (`part_of="User"`) to avoid circular dependencies
2. **Use @use_case decorator**: Mark each use case method with `@use_case` to get automatic UnitOfWork wrapping. Import from `protean`: `from protean import use_case`
3. **Implicit UnitOfWork**: Each `@use_case` method runs within a UnitOfWork automatically. A Unit of Work is one real database transaction. On success, changes are committed; on exception, everything is rolled back
4. **Direct invocation inside a domain context**: Instantiate and call directly, after `domain.init()` and inside `with domain.domain_context():`. A use case called with no active domain context raises `ConfigurationError`. NOT dispatched via `domain.process()`
5. **Synchronous return values**: Application services always execute synchronously and return values to the caller immediately
6. **Thin orchestration only**: Load aggregate, call domain method, persist result. No business logic in the service; push decisions into aggregates or domain services
7. **One use case per method**: Each method represents a single, cohesive business operation
8. **Persist one aggregate**: A use case method should persist only one aggregate, and that includes two instances of the same type. The Unit of Work does not enforce this: it can hold changes to several aggregates. It is a design rule. Change other aggregates through events (see "Persisting multiple aggregates" below)
9. **Use case naming**: Name methods after business operations: `register_user`, `place_order`, `cancel_subscription`
10. **No handle_error hook**: Unlike command/event handlers, exceptions propagate directly to the caller. The UnitOfWork rolls back, then the exception re-raises
11. **No retry**: `@use_case` runs the method once. A version conflict (`ExpectedVersionError`) reaches the caller like any other exception. Command and event handlers retry it; use cases do not

## Application service options

| Option | Purpose | Required | Default |
|--------|---------|----------|---------|
| `part_of` | Associate service with an aggregate class | Yes | None |

## Quick example: Multiple use cases

```python
@domain.aggregate
class Account:
    email: String(required=True)
    status: String(default="INACTIVE")

    def activate(self):
        self.status = "ACTIVE"

    def deactivate(self):
        self.status = "INACTIVE"

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

A use case opens a Unit of Work, so it needs an initialized domain and an active domain context. Without the context, the call raises `ConfigurationError`.

```python
domain.init(traverse=False)

# Direct instantiation and call (NOT domain.process())
with domain.domain_context():
    svc = AccountServices()
    account_id = svc.create_account(email="user@example.com")
    svc.activate_account(account_id=account_id)
```

In tests, the `test_domain` fixture activates a domain context for you.

## The @use_case decorator

The `@use_case` decorator has three responsibilities:

1. **UnitOfWork wrapping**: The method body executes inside a `UnitOfWork` context. Commits on success, rolls back on exception.
2. **Execution logging**: Logs invocation at INFO level for traceability.
3. **Domain context check**: Raises `ConfigurationError` when no domain context is active.

Only `@use_case`-decorated methods get UoW treatment. Regular helper methods do not:

```python
from protean.exceptions import ValidationError
from protean.fields import List

@domain.aggregate
class Order:
    items: List(content_type=String)

    @classmethod
    def place(cls, items: list) -> "Order":
        if not items:
            raise ValidationError({"items": ["Order must have items"]})
        return cls(items=items)

@domain.application_service(part_of=Order)
class OrderServices:
    @use_case
    def place_order(self, items: list) -> Identifier:
        # Runs inside UnitOfWork
        order = Order.place(items=self._clean_items(items))
        current_domain.repository_for(Order).add(order)
        return order.id

    def _clean_items(self, items: list) -> list:
        # Regular helper - NO UnitOfWork wrapping
        return [item.strip() for item in items if item.strip()]
```

## Error handling

Exceptions propagate directly to the caller. The UnitOfWork auto-rolls back. The caller, here an API handler, maps them to responses:

```python
def register_user_endpoint(email: str, name: str):
    with domain.domain_context():
        try:
            user_id = UserServices().register_user(email=email, name=name)
        except ValidationError as exc:
            return 400, exc.messages
    # Other exceptions reach the web framework, which returns a 500
    return 201, {"id": user_id}

status, body = register_user_endpoint(email="john@example.com", name="John")
assert status == 201

status, body = register_user_endpoint(email=None, name="John")
assert status == 400
```

## Application services vs. command handlers

| Aspect | Application Service | Command Handler |
|--------|-------------------|-----------------|
| Invocation | Direct: `svc.method()` | Via dispatch: `domain.process(cmd)` |
| Return values | Always synchronous | Depends on sync/async mode |
| Error handling | Exceptions propagate to caller | `handle_error` hook available |
| Version conflict | Raised to the caller, no retry | Retried by default |
| Architecture | Pure DDD | CQRS |
| Input | Plain Python arguments | Command DTO |

When evolving to CQRS, application services are replaced by commands + command handlers.

## Common mistakes

### Missing part_of

```python
# fragment
@domain.application_service  # Wrong! Missing part_of
class ProfileServices:
    pass
```

Instead: Always specify part_of with the aggregate class

```python
@domain.application_service(part_of=User)  # Correct!
class ProfileServices:
    pass
```

### Putting business logic in the service

```python
# fragment
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
# fragment
@use_case
def place_order(self, items: list) -> Identifier:
    order = Order.place(items=items)  # Aggregate enforces rules
    current_domain.repository_for(Order).add(order)
    return order.id
```

### Using domain.process() instead of direct invocation

```python
# fragment
# Wrong! Application services are not dispatched via domain.process()
domain.process(some_service_call)
```

Instead: Instantiate and call directly, inside a domain context

```python
with domain.domain_context():
    svc = OrderServices()
    order_id = svc.place_order(items=["book", "pen"])
```

### Wrapping in UnitOfWork manually

```python
# fragment
@use_case
def register_user(self, email, name):
    with UnitOfWork():  # Unnecessary! Already implicit via @use_case
        user = User(email=email, name=name)
        ...
```

The inner Unit of Work joins the one `@use_case` opened, so it adds nothing. Instead: Let `@use_case` handle the UnitOfWork

```python
# fragment
@use_case
def register_user(self, email, name):
    user = User(email=email, name=name)
    current_domain.repository_for(User).add(user)
    return user.id
```

### Persisting multiple aggregates

```python
# fragment
@use_case
def transfer_funds(self, from_id, to_id, amount):
    from_acct = current_domain.repository_for(Account).get(from_id)
    to_acct = current_domain.repository_for(Account).get(to_id)
    from_acct.debit(amount)
    to_acct.credit(amount)
    current_domain.repository_for(Account).add(from_acct)
    current_domain.repository_for(Account).add(to_acct)  # Wrong!
```

This code runs: the Unit of Work would commit both accounts in one transaction. It is still wrong, because one aggregate per transaction is a design rule that the Unit of Work does not enforce. Two instances of the same aggregate type count as two aggregates.

Instead: Change one account in the use case. The account raises an event (for example `FundsDebited`). An event handler in Account's cluster reacts to it and issues a command (for example `CreditFunds`). That command's handler credits the other account, and skips a transfer it has already applied, because events can be delivered more than once. The `event-handler` skill's cross-aggregate reference shows this pattern in full.

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
