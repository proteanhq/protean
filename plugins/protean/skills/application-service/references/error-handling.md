# Error Handling in Application Services

An application service has no `handle_error` hook, unlike command and event handlers. Its caller is always present, so exceptions propagate to it directly.

## Exception Flow

When an exception occurs inside a `@use_case` method:

1. The `UnitOfWork` context manager rolls back all uncommitted changes
2. The exception re-raises to the caller

On providers with transactions, and on the in-memory provider, the rollback leaves no partial state. Elasticsearch is the exception: [Unit of Work](unit-of-work.md) covers what a rollback undoes on each provider.

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

Catch exceptions in the API layer (controller), and let the use case raise them. A use case needs an initialized domain and an active domain context, so the controller opens one:

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

Raise domain errors from the aggregate, as `User.register` does here. Logging failed operations and sending error notifications also belong in the API layer. A use case that catches and swallows an exception hides the failure from its caller: [Anti-patterns](anti-patterns.md) shows the wrong and right versions.

## No Retry on Version Conflicts

`@use_case` runs the method once. If a save hits a version conflict (`ExpectedVersionError`, raised when another writer changed the aggregate first), the Unit of Work rolls back and the exception reaches the caller. A caller that wants a retry calls the use case again, which loads the aggregate fresh. [Unit of Work](unit-of-work.md) compares this with the retries `@handle` makes.

See [Error Handling Example](../assets/application_service_error_handling.py) for a complete runnable example.
