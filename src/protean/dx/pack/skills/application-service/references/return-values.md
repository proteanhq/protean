# Return Values from Application Services

Application services execute synchronously and always return values directly to the caller. A command handler returns a value only in synchronous mode, so an application service suits a request-response workflow where the caller needs a result at once: a new ID, a status, an authentication token.

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

- `register_user` returns the new aggregate's identifier. The caller typically needs it to reach the new resource
- `activate_user` returns `None`. A mutation like activation or deactivation needs no result
- `get_user` returns the loaded aggregate

Return IDs or simple data where you can. The controller shapes the HTTP response from them.

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

See [Return Values Example](../assets/application_service_return_values.py) for a complete runnable example.
