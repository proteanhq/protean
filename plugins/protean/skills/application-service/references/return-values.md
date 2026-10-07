# Return Values from Application Services

Application services execute synchronously and always return values directly to the caller. This is one of their key advantages over command handlers for request-response workflows.

The examples on this page use this aggregate and service. Each pattern below is one of its methods:

```python
from protean.fields import Identifier, String

@domain.aggregate
class User:
    email: String(required=True)
    name: String()
    status: String(default="INACTIVE")

    @classmethod
    def register(cls, email, name):
        return cls(email=email, name=name)

    def activate(self):
        self.status = "ACTIVE"

@domain.application_service(part_of=User)
class UserServices:
    @use_case
    def register_user(self, email: str, name: str) -> Identifier:
        user = User.register(email, name)
        current_domain.repository_for(User).add(user)
        return user.id

    @use_case
    def activate_user(self, user_id: Identifier) -> None:
        user = current_domain.repository_for(User).get(user_id)
        user.activate()
        current_domain.repository_for(User).add(user)

    @use_case
    def get_user(self, user_id: Identifier) -> User:
        return current_domain.repository_for(User).get(user_id)
```

## Common Patterns

### Returning a new entity ID

```python
# fragment
@use_case
def register_user(self, email: str, name: str) -> Identifier:
    user = User.register(email, name)
    current_domain.repository_for(User).add(user)
    return user.id  # Return the new entity's identifier
```

### No return value for mutative operations

```python
# fragment
@use_case
def activate_user(self, user_id: Identifier) -> None:
    user = current_domain.repository_for(User).get(user_id)
    user.activate()
    current_domain.repository_for(User).add(user)
    # No return value needed
```

### Returning loaded entities

```python
# fragment
@use_case
def get_user(self, user_id: Identifier) -> User:
    return current_domain.repository_for(User).get(user_id)
```

### Using the return values

The caller gets each value back as soon as the method returns. Call the service inside a domain context:

```python
domain.init(traverse=False)

with domain.domain_context():
    svc = UserServices()
    user_id = svc.register_user(email="jane@example.com", name="Jane")
    svc.activate_user(user_id)
    user = svc.get_user(user_id)
    assert user.status == "ACTIVE"
```

## Comparison with Command Handlers

| Aspect | Application Service | Command Handler |
|--------|-------------------|-----------------|
| Return mechanism | Direct return value | Return depends on sync/async mode |
| Caller always gets result | Yes | Only in synchronous mode |
| Suitable for | Request-response | Event-driven / async workflows |

Application services are ideal for workflows where the caller needs immediate feedback, such as a newly created ID, a status update, or an authentication token.

## Best Practices

1. **Return identifiers for create operations**: The caller typically needs the ID to navigate to the new resource
2. **Return None for simple mutations**: When the caller doesn't need a result (activation, deactivation)
3. **Keep return values simple**: Return IDs or simple data, not complex aggregate graphs
4. **Use the API layer for response shaping**: Transform return values into HTTP responses in the controller, not the service

See [Return Values Example](../assets/application_service_return_values.py) for a complete runnable example.
