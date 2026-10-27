# Application Service Anti-patterns

The examples on this page use these aggregates and services. Each "Correct" method below is one of these methods:

```python
from protean.exceptions import ValidationError
from protean.fields import Decimal, Identifier, List, String

@domain.aggregate
class User:
    email: String(required=True)
    name: String()
    status: String(default="INACTIVE")

    def activate(self):
        self.status = "ACTIVE"

@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    items: List(content_type=String)

    @classmethod
    def place(cls, customer_id, items):
        if not items:
            raise ValidationError({"items": ["Order must have items"]})
        return cls(customer_id=customer_id, items=items)

@domain.event(part_of="Account")
class FundsDebited:
    account_id: Identifier(required=True)
    to_account_id: Identifier(required=True)
    amount: Decimal(precision=19, scale=4, required=True)

@domain.aggregate
class Account:
    balance: Decimal(precision=19, scale=4, default=0)

    def debit(self, amount, to_account_id):
        self.balance -= amount
        self.raise_(
            FundsDebited(account_id=self.id, to_account_id=to_account_id, amount=amount)
        )

@domain.application_service(part_of=User)
class UserServices:
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

@domain.application_service(part_of=Order)
class OrderServices:
    @use_case
    def place_order(self, items, customer_id):
        order = Order.place(customer_id=customer_id, items=items)
        current_domain.repository_for(Order).add(order)
        return order.id

@domain.application_service(part_of=Account)
class AccountServices:
    @use_case
    def transfer_funds(self, from_id, to_id, amount):
        from_acct = current_domain.repository_for(Account).get(from_id)
        from_acct.debit(amount, to_account_id=to_id)
        current_domain.repository_for(Account).add(from_acct)
```

## 1. Business Logic in the Service

Application services should orchestrate, not decide. Business rules belong in aggregates or domain services.

```python
# fragment
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
# fragment
# Correct - delegate to aggregate
@use_case
def place_order(self, items, customer_id):
    order = Order.place(customer_id=customer_id, items=items)
    current_domain.repository_for(Order).add(order)
    return order.id
```

## 2. Persisting Multiple Aggregates

A use case method should persist only one aggregate root, and two instances of the same type count as two. The Unit of Work does not stop you: it commits both in one transaction. Use domain events for cross-aggregate coordination.

```python
# fragment
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
# fragment
# Correct - persist one, use events for the other
@use_case
def transfer_funds(self, from_id, to_id, amount):
    from_acct = current_domain.repository_for(Account).get(from_id)
    from_acct.debit(amount, to_account_id=to_id)  # raises FundsDebited
    current_domain.repository_for(Account).add(from_acct)
```

An event handler in Account's cluster reacts to `FundsDebited` and issues a command (for example `CreditFunds`). That command's handler credits the other account and skips a transfer it has already applied, because an event can be delivered more than once. The `event-handler` skill's cross-aggregate reference shows the full pattern.

## 3. Missing part_of Association

Every application service must declare which aggregate it operates on.

```python
# fragment
# Wrong - will raise IncorrectUsageError
@domain.application_service
class ProfileServices:
    ...
```

Registration raises ``IncorrectUsageError: Application Service `ProfileServices` needs to be associated with an aggregate``.

```python
# Correct
@domain.application_service(part_of=User)
class ProfileServices:
    pass
```

## 4. Multiple Use Cases in One Method

Each method should represent a single, cohesive business operation.

```python
# fragment
# Wrong - combining multiple operations
@use_case
def register_and_activate(self, email, name):
    user = User(email=email, name=name)
    user.activate()  # Mixing two operations
    current_domain.repository_for(User).add(user)
    return user.id
```

```python
# fragment
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

## 5. Catching and Swallowing Exceptions

Let exceptions propagate. The UoW handles rollback, and the caller handles the error.

```python
# fragment
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
# fragment
# Correct - let exceptions propagate
@use_case
def register_user(self, email, name):
    user = User(email=email, name=name)
    current_domain.repository_for(User).add(user)
    return user.id
# Caller catches and handles exceptions appropriately
```

See [Error Handling Example](../assets/application_service_error_handling.py) for a complete runnable example.
