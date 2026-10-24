# Anti-corruption Layer Pattern

Subscribers serve as anti-corruption layers at the domain boundary, translating external system schemas into the domain's own language.

## Overview

The anti-corruption layer (ACL) is the canonical DDD use case for subscribers. External systems have their own naming conventions, data formats, and event schemas. The subscriber is the ONLY place in your domain that knows about these external formats. Everything downstream works with your domain's own commands and events.

## Walkthrough

### External Format (ERP System)

```json
{
    "event_type": "user.created",
    "data": {
        "userId": "USR-001",
        "firstName": "Alice",
        "lastName": "Johnson",
        "emailAddress": "alice@example.com"
    }
}
```

The external system uses camelCase, nested `data` objects, and its own naming conventions (`emailAddress` vs `email`, separate first/last name).

### Domain Aggregate and Command

```python
@domain.aggregate
class Customer:
    name: String(required=True)
    email: String(required=True)
    source: String(default="direct")

    def update_email(self, email: str) -> None:
        self.email = email

@domain.command(part_of="Customer")
class RegisterCustomer:
    customer_id: Identifier(required=True)
    name: String(required=True)
    email: String(required=True)
    source: String(default="erp")
```

The aggregate and the command use the domain's own language and carry nothing from the external format.

### The Subscriber (ACL)

```python
@domain.subscriber(stream="erp_user_events")
class ERPUserSubscriber:
    def __call__(self, payload: dict) -> None:
        event_type = payload.get("event_type", "")
        if event_type == "user.created":
            self._handle_user_created(payload["data"])

    def _handle_user_created(self, data: dict) -> None:
        command = RegisterCustomer(
            customer_id=data["userId"],
            name=f"{data['firstName']} {data['lastName']}",
            email=data["emailAddress"],
            source="erp",
        )
        domain.process(command)
```

### Why This Matters

If the external ERP system changes its format (e.g., renames `emailAddress` to `email_addr`), you only need to update the subscriber. The domain command, command handler, and aggregate remain untouched.

## Variations

### Multiple External Event Types

A single subscriber can handle multiple event types from the same external system:

```python
@domain.subscriber(stream="erp_events")
class ERPSubscriber:
    def __call__(self, payload: dict) -> None:
        event_type = payload.get("event_type", "")
        if event_type == "user.created":
            self._handle_user_created(payload["data"])
        elif event_type == "user.updated":
            self._handle_user_updated(payload["data"])
```

### Direct Aggregate Operations

For simpler cases, the subscriber can operate on aggregates directly instead of dispatching commands:

```python
@domain.subscriber(stream="external_updates")
class SimpleSubscriber:
    def __call__(self, payload: dict) -> None:
        repo = domain.repository_for(Customer)
        customer = repo.get(payload["id"])
        customer.update_email(payload["new_email"])
        repo.add(customer)
```

## Related

- [Basic Subscriber](./basic-subscriber.md): Simpler pattern without command dispatch
- [Error Handling](./error-handling.md): Handling failures in translation
- `command`: Commands are the domain language subscribers translate into
- `command-handler`: Processes the commands dispatched by subscribers
