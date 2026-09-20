# Error Handling in Application Services

Application services handle errors differently from command and event handlers. Because they execute synchronously with the caller always present, there is no `handle_error` hook. Exceptions propagate directly.

## Exception Flow

When an exception occurs inside a `@use_case` method:

1. The `UnitOfWork` context manager rolls back all uncommitted changes
2. The exception re-raises to the caller
3. No partial state is persisted

```python
@domain.application_service(part_of=User)
class UserServices:
    @use_case
    def register_user(self, email: str, name: str) -> Identifier:
        user = User.register(email, name)  # May raise ValidationError
        current_domain.repository_for(User).add(user)
        return user.id
```

## Caller-Side Error Handling

Handle exceptions in the API layer (controller), not in the application service:

```python
# In the API layer
try:
    svc = UserServices()
    user_id = svc.register_user(email="john@example.com", name="John Doe")
except ValidationError as exc:
    # Handle validation errors (e.g., return 400 response)
    ...
except Exception as exc:
    # Handle unexpected errors (e.g., return 500 response)
    ...
```

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

The UoW ensures atomicity — if any part of the use case fails, ALL changes are rolled back:

```python
@use_case
def register_user(self, email, name):
    user = User(email=email, name=name)
    current_domain.repository_for(User).add(user)
    # If this next line raises, the user addition is rolled back
    user.raise_(Registered(user_id=user.id, email=email, name=name))
    return user.id
```

See [Error Handling Example](../assets/application_service_error_handling.py) for a complete runnable example.
