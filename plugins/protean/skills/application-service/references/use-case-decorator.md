# The @use_case Decorator

The `@use_case` decorator is the primary mechanism for marking methods as use case entry points in an application service.

## Import

```python
from protean import use_case
```

## Responsibilities

### 1. UnitOfWork Wrapping

Every method decorated with `@use_case` is automatically enclosed in a `UnitOfWork` context:

- If the method completes successfully, the UoW **commits** all pending changes (aggregate mutations, event publications, persistence operations)
- If an exception is raised, the UoW **rolls back** all changes before re-raising the exception

```python
from protean.fields import Identifier, String

@domain.aggregate
class User:
    email: String(required=True)
    name: String()

@domain.application_service(part_of=User)
class UserServices:
    @use_case
    def register_user(self, email: str, name: str) -> Identifier:
        # Everything inside here runs within a UnitOfWork
        user = User(email=email, name=name)
        current_domain.repository_for(User).add(user)
        return user.id
```

### 2. Execution Logging

The decorator logs each invocation at the INFO level:

```
INFO: Executing use case: register_user
```

This provides traceability for debugging and auditing.

### 3. Domain Context Check

The decorator checks for an active domain context before it opens the Unit of Work. Without one, the call raises `ConfigurationError` and names the use case. Call use cases after `domain.init()` and inside `with domain.domain_context():`. In tests, the `test_domain` fixture activates a context for you.

## Internal Implementation

```python
# fragment
def use_case(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger.info(f"Executing use case: {func.__name__}")
        if not has_domain_context():
            raise ConfigurationError(...)
        with UnitOfWork():
            return func(*args, **kwargs)
    setattr(wrapper, "_use_case", True)
    return wrapper
```

The `_use_case` attribute is set on the wrapper function to mark it as a use case method. The wrapper does not retry: a version conflict (`ExpectedVersionError`) reaches the caller after the rollback. `@handle` is the one that retries, on command handlers, event handlers, process managers and projectors alike.

## Important Notes

- Only `@use_case`-decorated methods receive UoW treatment
- Regular (non-decorated) methods on the same class do NOT get automatic transaction management
- You can add helper methods without the decorator for internal logic
- Do NOT manually wrap in `UnitOfWork` inside a `@use_case` method: it is already wrapped. A Unit of Work opened inside another one joins it, so the inner one adds nothing
- A use case that calls another use case runs both in one transaction, for the same reason

## Example: Mixed Methods

```python
from protean.fields import Integer, List, ValueObject

@domain.value_object
class LineItem:
    sku: String(required=True)
    quantity: Integer(default=1)

@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    items: List(content_type=ValueObject(LineItem))

    @classmethod
    def place(cls, customer_id, items):
        return cls(customer_id=customer_id, items=items)

@domain.application_service(part_of=Order)
class OrderServices:
    @use_case
    def place_order(self, customer_id: str, items: list) -> Identifier:
        # Wrapped in UnitOfWork
        validated_items = self._validate_items(items)
        order = Order.place(customer_id=customer_id, items=validated_items)
        current_domain.repository_for(Order).add(order)
        return order.id

    def _validate_items(self, items):
        # NOT wrapped in UnitOfWork: plain helper
        return [item for item in items if item.quantity > 0]
```

Call it inside a domain context:

```python
domain.init(traverse=False)

with domain.domain_context():
    order_id = OrderServices().place_order(
        customer_id="c-1",
        items=[LineItem(sku="BOOK-1", quantity=2), LineItem(sku="PEN-1", quantity=0)],
    )
    order = current_domain.repository_for(Order).get(order_id)
    assert [item.sku for item in order.items] == ["BOOK-1"]
```

See [Simple Service](../assets/application_service_simple.py) for a complete runnable example.
