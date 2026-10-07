# Error Handling in Application Services

Application services handle errors differently from command and event handlers. Because they execute synchronously with the caller always present, there is no `handle_error` hook. Exceptions propagate directly.

## Exception Flow

When an exception occurs inside a `@use_case` method:

1. The `UnitOfWork` context manager rolls back all uncommitted changes
2. The exception re-raises to the caller
3. No partial state is persisted

```python
from protean.exceptions import ValidationError
from protean.fields import Identifier, String

@domain.aggregate
class User:
    email: String(required=True)
    name: String(required=True)

    @classmethod
    def register(cls, email, name):
        return cls(email=email, name=name)  # Raises ValidationError on bad input

@domain.application_service(part_of=User)
class UserServices:
    @use_case
    def register_user(self, email: str, name: str) -> Identifier:
        user = User.register(email, name)  # May raise ValidationError
        current_domain.repository_for(User).add(user)
        return user.id
```

## Caller-Side Error Handling

Handle exceptions in the API layer (controller), not in the application service. The use case needs an initialized domain and an active domain context, so the controller opens one:

```python
domain.init(traverse=False)

# In the API layer
def register_user_endpoint(email: str, name: str):
    with domain.domain_context():
        try:
            user_id = UserServices().register_user(email=email, name=name)
        except ValidationError as exc:
            return 400, exc.messages  # Validation errors become a 400 response
    # Unexpected errors reach the web framework, which returns a 500
    return 201, {"id": user_id}

assert register_user_endpoint(email="john@example.com", name="John Doe")[0] == 201
assert register_user_endpoint(email=None, name="John Doe")[0] == 400
```

## No Retry on Version Conflicts

`@use_case` runs the method once. If a save hits a version conflict (`ExpectedVersionError`, raised when another writer changed the aggregate first), the Unit of Work rolls back and the exception reaches the caller. Command and event handlers behave differently: `@handle` retries a version conflict up to 3 more times by default. A caller that wants a retry calls the use case again, which loads the aggregate fresh.

## No handle_error Hook

Unlike command handlers and event handlers, application services do NOT have a `handle_error` classmethod:

| Element | Error Recovery Mechanism |
|---------|------------------------|
| Application Service | Exceptions propagate directly to caller |
| Command Handler | `handle_error(cls, exc, message)` classmethod |
| Event Handler | `handle_error(cls, exc, message)` classmethod |

This is because application services always have a synchronous caller present who can handle the exception.

## Best Practices

1. **Keep use case methods focused on orchestration**: Domain-level errors should be raised by the aggregate, not the service
2. **Let domain validation errors bubble up**: The API layer maps them to appropriate HTTP status codes
3. **Use the API layer for cross-cutting concerns**: Logging failed operations, sending error notifications, etc.
4. **Don't catch and swallow exceptions**: Let the UoW rollback mechanism do its job

## UnitOfWork Rollback Guarantee

The Unit of Work is one real database transaction, as [ADR-0027 (The Unit of Work is a real database transaction)](https://docs.proteanhq.com/adr/0027-unit-of-work-is-a-real-transaction/) describes. Writes reach the database inside the transaction, but nothing is committed or visible to other connections until the Unit of Work commits. If any part of the use case fails, the rollback undoes ALL its writes:

```python
# fragment
@use_case
def register_user(self, email, name):
    user = User(email=email, name=name)
    current_domain.repository_for(User).add(user)
    # If this next line raises, the user addition is rolled back
    user.raise_(Registered(user_id=user.id, email=email, name=name))
    return user.id
```

See [Error Handling Example](../assets/application_service_error_handling.py) for a complete runnable example.
