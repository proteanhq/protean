# Application Service Anti-patterns

Common mistakes when implementing application services and how to avoid them.

## 1. Business Logic in the Service

Application services should orchestrate, not decide. Business rules belong in aggregates or domain services.

```python
# Wrong - business logic in the service
@use_case
def place_order(self, items, customer_id):
    if len(items) == 0:
        raise ValidationError("Order must have items")
    total = sum(item.price * item.quantity for item in items)
    if total > 10000:
        raise ValidationError("Order exceeds limit")
    order = Order(customer_id=customer_id, items=items, total=total)
    current_domain.repository_for(Order).add(order)
    return order.id
```

```python
# Correct - delegate to aggregate
@use_case
def place_order(self, items, customer_id):
    order = Order.place(customer_id=customer_id, items=items)
    current_domain.repository_for(Order).add(order)
    return order.id
```

## 2. Persisting Multiple Aggregates

A use case method should persist only one aggregate root. Use domain events for cross-aggregate coordination.

```python
# Wrong - persisting two aggregates
@use_case
def transfer_funds(self, from_id, to_id, amount):
    from_acct = current_domain.repository_for(Account).get(from_id)
    to_acct = current_domain.repository_for(Account).get(to_id)
    from_acct.debit(amount)
    to_acct.credit(amount)
    current_domain.repository_for(Account).add(from_acct)
    current_domain.repository_for(Account).add(to_acct)  # Anti-pattern!
```

```python
# Correct - persist one, use events for the other
@use_case
def transfer_funds(self, from_id, to_id, amount):
    from_acct = current_domain.repository_for(Account).get(from_id)
    from_acct.debit(amount, to_account_id=to_id)
    # Aggregate raises FundsDebited event, event handler credits to_acct
    current_domain.repository_for(Account).add(from_acct)
```

## 3. Manual UnitOfWork Wrapping

The `@use_case` decorator already wraps the method in a UnitOfWork.

```python
# Wrong - redundant UoW
@use_case
def register_user(self, email, name):
    with UnitOfWork():
        user = User(email=email, name=name)
        current_domain.repository_for(User).add(user)
        return user.id
```

```python
# Correct - UoW is implicit
@use_case
def register_user(self, email, name):
    user = User(email=email, name=name)
    current_domain.repository_for(User).add(user)
    return user.id
```

## 4. Using domain.process() for Invocation

Application services are called directly, not dispatched through the domain's command processing pipeline.

```python
# Wrong - this is the command handler pattern
result = domain.process(some_command, asynchronous=False)
```

```python
# Correct - direct invocation
svc = UserServices()
user_id = svc.register_user(email="user@example.com", name="User")
```

## 5. Missing part_of Association

Every application service must declare which aggregate it operates on.

```python
# Wrong - will raise IncorrectUsageError
@domain.application_service
class UserServices:
    ...
```

```python
# Correct
@domain.application_service(part_of=User)
class UserServices:
    ...
```

## 6. Multiple Use Cases in One Method

Each method should represent a single, cohesive business operation.

```python
# Wrong - combining multiple operations
@use_case
def register_and_activate(self, email, name):
    user = User(email=email, name=name)
    user.activate()  # Mixing two operations
    current_domain.repository_for(User).add(user)
    return user.id
```

```python
# Correct - separate use case methods
@use_case
def register_user(self, email, name):
    user = User(email=email, name=name)
    current_domain.repository_for(User).add(user)
    return user.id

@use_case
def activate_user(self, user_id):
    user = current_domain.repository_for(User).get(user_id)
    user.activate()
    current_domain.repository_for(User).add(user)
```

## 7. Catching and Swallowing Exceptions

Let exceptions propagate — the UoW handles rollback, and the caller handles the error.

```python
# Wrong - swallowing exceptions
@use_case
def register_user(self, email, name):
    try:
        user = User(email=email, name=name)
        current_domain.repository_for(User).add(user)
        return user.id
    except Exception:
        return None  # Caller has no idea what went wrong
```

```python
# Correct - let exceptions propagate
@use_case
def register_user(self, email, name):
    user = User(email=email, name=name)
    current_domain.repository_for(User).add(user)
    return user.id
# Caller catches and handles exceptions appropriately
```

See [Error Handling Example](../assets/application_service_error_handling.py) for a complete runnable example.
