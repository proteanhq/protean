# Troubleshooting

A cookbook of common issues and how to debug them. For error classification
patterns in production, see
[Classify Async Processing Errors](../patterns/classify-async-processing-errors.md).

The examples on this page use this small order domain:

```python
--8<-- "reference/troubleshooting/001.py:model"
```

---

## Command is accepted but nothing happens

**Symptoms:** `domain.process()` returns without error, but the aggregate
isn't created or updated.

**Check 1: Is there a handler registered?**

```python
--8<-- "reference/troubleshooting/001.py:check_handler"
```

If this returns `None`, the handler isn't registered. Verify:

- The handler is decorated with `@domain.command_handler(part_of=YourAggregate)`
- The handler file is inside the domain's discovery path
- `domain.init()` was called after registration

**Check 2: Is the handler actually persisting?**

Command handlers must explicitly save via the repository:

```python
--8<-- "reference/troubleshooting/001.py:command_handler"
```

**Check 3: Is event processing set to sync for tests?**

In tests, events are processed asynchronously by default. If your test
expects immediate side effects, configure sync processing:

```python
--8<-- "reference/troubleshooting/001.py:sync_config"
```

Or use the `DomainFixture` which handles this automatically.

---

## Event handler doesn't fire

**Symptoms:** An aggregate raises an event, but the event handler's method
is never called.

**Check 1: Is the event raised inside the aggregate?**

Events must be raised with `self.raise_()` inside an aggregate method:

```python
--8<-- "reference/troubleshooting/001.py:order"
```

Creating an event object does nothing. It must be raised.

**Check 2: Is the handler wired to the right aggregate?**

```python
--8<-- "reference/troubleshooting/001.py:event_handler"
```

If the event belongs to `Order` but the handler says `part_of=Customer`,
it won't receive the event.

**Check 3: Is event processing async?**

In production, events flow through the outbox and are processed by the
server. In tests, set `event_processing = "sync"` or use the Engine in
test mode:

```python
--8<-- "reference/troubleshooting/001.py:engine"
```

---

## "No domain context" errors

**Symptoms:** A `UserWarning` that starts with `Working outside of domain
context.`, followed by an `AttributeError` that names a domain attribute, such
as `AttributeError: repository_for` or `AttributeError: config`. Protean warns
first, then the call fails because there is no current domain to read from.

**Cause:** Protean operations require an active domain context on the current
thread. This is usually set up by middleware (FastAPI) or fixtures (tests).

**Fix for FastAPI:**

```python
--8<-- "reference/troubleshooting/003.py:middleware"
```

**Fix for tests:**

```python
--8<-- "reference/troubleshooting/002.py:fixture"
```

**Fix for scripts or CLI tools:**

```python
--8<-- "reference/troubleshooting/001.py:script"
```

---

## Projection is empty or stale

**Symptoms:** Querying a projection returns no results or outdated data,
even though events have been raised.

**Check 1: Is the projector registered?**

```python
--8<-- "reference/troubleshooting/001.py:projection"
--8<-- "reference/troubleshooting/001.py:projector"
```

Verify the projector is decorated with `@domain.projector`, uses
`projector_for` pointing to the projection class, and lists the aggregates
whose events it handles in `aggregates`.

**Check 2: Are events flowing?**

In tests, ensure sync processing is active or run the engine:

```python
--8<-- "reference/troubleshooting/001.py:engine"
```

**Check 3: Is the projection database set up?**

Projections backed by a database need schema setup:

```python
--8<-- "reference/troubleshooting/001.py:setup_database"
```

---

## Subscriber doesn't receive messages

**Symptoms:** External messages are published to the broker, but the
subscriber's `__call__` method is never invoked.

**Check 1: Is the stream name correct?**

The subscriber's `stream` must match the broker stream/topic being published
to:

```python
--8<-- "reference/troubleshooting/001.py:subscriber"
```

**Check 2: Is the broker configured?**

Verify your `domain.toml` has a broker configured:

```toml
[brokers.default]
provider = "redis"
URI = "redis://localhost:6379/0"
```

**Check 3: Is the server running?**

Subscribers are processed by the Protean server, not inline. Start it with:

```bash
protean server --domain .
```

For tests, use test mode to process messages synchronously.

---

## Aggregate validation errors

**Symptoms:** `ValidationError` when creating or updating an aggregate.

**Debugging approach:**

```python
--8<-- "reference/troubleshooting/001.py:validation"
```

The `messages` dict maps field names to lists of error strings. Common
causes:

- **Missing required fields:** Fields with `required=True` must be provided
- **Invariant violations:** `@invariant.post` checks run after every mutation
- **Value object validation:** Embedded value objects validate their own
  constraints

!!! warning "`messages` is not always a dict"

    Field validation always produces the `dict[str, list[str]]` above, so code
    handling *that* can index it safely. But `ValidationError` carries whatever
    it was raised with, and an invariant or a domain service is free to raise
    `ValidationError("Order is already shipped")`. Then `messages` is a plain
    `str`, and a list raises it as a `list[str]`. A blanket
    `except ValidationError` that does `e.messages.items()` will fail on those.

    ```python
    # fragment
    except ValidationError as e:
        if isinstance(e.messages, dict):
            for field, errors in e.messages.items():
                ...
        else:  # a str or a list[str] raised by domain code
            ...
    ```


---

## Message tracing and debugging event chains

When a command triggers a chain of events and handlers, use Protean's
built-in tracing to follow the full causal chain.

**From the CLI:**

```bash
# Trace a specific correlation ID
protean events trace <correlation_id> --domain .
```

**Programmatically:**

```python
--8<-- "reference/troubleshooting/001.py:causation_tree"
```

**Supply correlation IDs from API boundaries:**

```python
--8<-- "reference/troubleshooting/003.py:endpoint"
```

See [Message Tracing](../guides/domain-behavior/message-tracing.md) for the full
guide.

---

## Common CLI debugging commands

```bash
# Check subscription status and lag
protean subscriptions --domain .

# Inspect dead letter queue
protean dlq list --domain .

# View recent events for an aggregate
protean events list --stream order-<aggregate_id> --domain .

# Launch the observatory dashboard
protean observatory --domain .
```

---

## Tests pass locally but fail in CI

**Common causes:**

1. **Missing Docker services:** Broker/database tests need Redis,
   PostgreSQL, etc. Use `make up` or configure CI to start services.

2. **Async timing:** Tests relying on async processing may need explicit
   engine runs. Use `engine.run()` in test mode rather than `time.sleep()`.

3. **Database state leakage:** Ensure each test starts clean. The
   `DomainFixture` handles this, but custom fixtures might not.

4. **Port conflicts:** If multiple CI jobs run in parallel, broker/database
   ports may collide. Use unique port mappings per job.

---

## Getting more help

- Check the [patterns](../patterns/index.md) for architectural guidance
- Review the [API reference](../api/index.md) for detailed method signatures
- File issues at [github.com/proteanhq/protean](https://github.com/proteanhq/protean/issues)
