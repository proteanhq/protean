# Return Values from Application Services

Application services execute synchronously and always return values directly to the caller. This is one of their key advantages over command handlers for request-response workflows.

## Common Patterns

### Returning a new entity ID

```python
@use_case
def register_user(self, email: str, name: str) -> Identifier:
    user = User.register(email, name)
    current_domain.repository_for(User).add(user)
    return user.id  # Return the new entity's identifier
```

### No return value for mutative operations

```python
@use_case
def activate_user(self, user_id: Identifier) -> None:
    user = current_domain.repository_for(User).get(user_id)
    user.activate()
    current_domain.repository_for(User).add(user)
    # No return value needed
```

### Returning loaded entities

```python
@use_case
def get_user(self, user_id: Identifier) -> User:
    return current_domain.repository_for(User).get(user_id)
```

## Comparison with Command Handlers

| Aspect | Application Service | Command Handler |
|--------|-------------------|-----------------|
| Return mechanism | Direct return value | Return depends on sync/async mode |
| Caller always gets result | Yes | Only in synchronous mode |
| Suitable for | Request-response | Event-driven / async workflows |

Application services are ideal for workflows where the caller needs immediate feedback — returning a newly created ID, a status update, or an authentication token.

## Best Practices

1. **Return identifiers for create operations**: The caller typically needs the ID to navigate to the new resource
2. **Return None for simple mutations**: When the caller doesn't need a result (activation, deactivation)
3. **Keep return values simple**: Return IDs or simple data, not complex aggregate graphs
4. **Use the API layer for response shaping**: Transform return values into HTTP responses in the controller, not the service

See [Return Values Example](../assets/application_service_return_values.py) for a complete runnable example.
