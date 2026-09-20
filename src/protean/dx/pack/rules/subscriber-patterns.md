---
description: Subscriber patterns — external message consumption, raw dict payloads, and ACL boundary rules
globs: "**/*.py"
---

# Subscriber Patterns

## `__call__` with Raw Dict, Not `@handle`

Subscribers implement `__call__(self, payload: dict)`, not `@handle`. The payload is
always a raw dict — subscribers are the anti-corruption layer (ACL) at the domain boundary:

```python
@domain.subscriber(channel="orders")
class ExternalOrderSubscriber:
    def __call__(self, payload: dict) -> None:
        # Translate external format to domain command
        command = PlaceOrder(
            customer_id=payload["customer"],
            product_id=payload["item"],
            quantity=payload["qty"],
        )
        current_domain.process(command)
```

## `message_processing` Config (Not `event_processing`)

For synchronous subscriber testing, use `message_processing` — this is separate from
`event_processing`:

```python
domain.config["message_processing"] = "sync"
```

## ACL Boundary

If an external message has no `correlation_id`, the subscriber auto-generates one. This
is correct — the subscriber represents a fresh transaction boundary.

## No Business Logic in Subscribers

Subscribers translate and forward. Business logic lives in the aggregate/handler that
processes the resulting command.
