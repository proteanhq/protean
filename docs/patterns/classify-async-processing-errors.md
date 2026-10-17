# Classify and Handle Async Processing Errors

## The Problem

An e-commerce platform uses a projector to maintain an `OrderDashboard`
projection:

```python
--8<-- "patterns/classify-async-processing-errors/001.py:imports"
--8<-- "patterns/classify-async-processing-errors/001.py:model"
--8<-- "patterns/classify-async-processing-errors/001.py:problem"
```

On Tuesday, the Elasticsearch cluster is temporarily unreachable. The
projector fails on an `OrderShipped` event with a connection timeout. The
engine logs the exception, calls the default (no-op) `handle_error`, and
moves on. The order stays stuck at "placed" in the dashboard while the write
side has already moved to "shipped".

Nobody notices. There are no alerts, no DLQ entries, no metrics spike.

On Thursday, a developer deploys a new event version that adds a `currency`
field to `OrderPlaced`. The projector has not been updated. Every new order
fails with a schema mismatch, but the team only monitors HTTP error rates.
Async handler failures are invisible.

By Friday, the read model is 72 hours behind the write model. Customer
support is working from wrong data.

This is not exotic. It is the *default behavior* of any async pipeline that
logs errors and continues. The Protean engine is resilient (it never crashes on
a handler exception) but resilience without observability is silent data drift.

The root causes are different in kind:

- The Elasticsearch timeout is **transient**. Retrying would succeed.
- The schema mismatch is a **data error**. Retrying will never fix it.
- A bug in the projector's logic is a **logic error**. It needs a code fix,
  not a retry.

Treating all three the same way (log and continue) is the real problem.

---

## The Pattern

Override `handle_error()` in every production handler. Classify each failure
into one of three categories and respond accordingly:

| Category | Examples | Strategy |
|----------|----------|----------|
| **Transient** | Network timeouts, lock contention, broker unavailability | Let the framework retry the message |
| **Data error** | Schema mismatch, missing fields, invalid payload | Route to DLQ for manual inspection, alert the team |
| **Logic error** | Business rule violations, incorrect calculations, unexpected `None` | Alert immediately, fix the code, replay |

The mental model:

```
Exception raised in handler
    |
    +-- Is it transient?
    |       Yes --> Log WARNING, let the framework retry it.
    |
    +-- Is it a data problem?
    |       Yes --> Send to DLQ. Alert the team.
    |
    +-- Is it a logic bug?
            Yes --> Alert immediately. Fix the code. Replay.
```

### Why this matters for projectors

Projectors maintain read models. A failed projector update means the read side
has diverged from the write side. Unlike a failed event handler (where the
consequence might be a delayed side effect) a failed projector creates
**stale data that users see**. This makes projector error handling especially
critical: a transient failure should retry quickly, a persistent failure
should alert immediately.

### The `handle_error` contract

Protean's `HandlerMixin` provides a `handle_error` classmethod that the
engine calls whenever a handler raises an exception:

```python
# fragment
@classmethod
def handle_error(cls, exc: Exception, message: Message) -> None:
    """Called by the engine when this handler raises an exception.

    The default implementation does nothing. Override to classify
    and respond to errors.
    """
```

The engine's processing flow:

1. `handler_cls._handle(message)` raises an exception.
2. The engine logs the exception with full traceback.
3. The `TraceEmitter` emits a `handler.failed` trace event.
4. `handler_cls.handle_error(exc, message)` is called inside a `try/except`:
   If *it* also fails, that secondary exception is logged but does not
   crash the engine.
5. Processing continues with the next message.

This means `handle_error` is your **classification hook**. It runs after the
failure is already recorded in traces and logs. Its job is to decide what
happens next: nothing (for transient errors the framework will retry), DLQ
routing, or immediate alerting.

---

## Applying the Pattern

### Classifying errors

Build helpers that recognize common failure signatures:

```python
--8<-- "patterns/classify-async-processing-errors/001.py:classifiers"
```

!!! warning "Classify the members of an `ExceptionGroup`"
    When an event handler or projector has several `@handle` methods for one
    event and more than one of them fails, `handle_error` receives an
    `ExceptionGroup` holding each failure. A classifier that only asks
    `isinstance(exc, ConnectionError)` sees the group, matches nothing, and
    treats a passing network blip as a logic error. Recurse into
    `exc.exceptions`, as the functions above do. `except*` matches a group too,
    but `handle_error` receives the exception as an argument rather than raising
    it, so reaching for `except*` means re-raising it inside a `try` first.

!!! note
    This classification is domain-specific. If your projection store is
    Elasticsearch, add `ConnectionTimeout` and `TransportError` to the
    transient list. If you use a third-party API, add its rate-limit
    and gateway-timeout exceptions.

### Transient errors: let the framework retry

Transient errors resolve themselves. Protean retries a failed message in two
places:

- **In the handler.** With `transient_retry` turned on (it is off by
  default), a handler that raises `ConnectionError`, `TimeoutError` or
  `SendError` runs again in place, with exponential backoff, before the
  failure leaves the handler. `handle_error` only sees the failure once these
  retries run out. See
  [Transient-failure retries](../guides/consume-state/event-handlers.md#transient-failure-retries).
- **In the subscription.** The subscription that delivered the message
  tries it again after a failure. `max_retries` (3 by default) sets when it
  gives up, and the two subscription types retry differently:
    - A stream subscription retries straight away, waiting
      `retry_delay_seconds` (1 second by default) between attempts. It stops
      after `max_retries` attempts in total, so 3 attempts by default.
    - An event store subscription moves past the failed message and retries
      it on a later recovery pass. A pass runs every
      `recovery_interval_seconds` (30 seconds by default) and waits
      `retry_delay_seconds` before each retry. It retries `max_retries` times
      after the first failure, so 4 attempts by default. With
      `enable_recovery` set to `False`, it does not retry at all.

The subscription retries every failure, whatever `handle_error` decides.
`handle_error` cannot stop a retry, and the engine calls it again after each
failed attempt. A data or logic error therefore reaches your alert more than
once, so deduplicate alerts by message id.

For transient errors, the best action in `handle_error` is minimal logging:

```python
--8<-- "patterns/classify-async-processing-errors/001.py:transient"
```

The handler is `part_of=Inventory`, but `OrderPlaced` belongs to `Order`. An
event handler reads its own aggregate's stream unless it sets
`stream_category`, so this one names the order stream. Without it, the engine
would never deliver `OrderPlaced` to the handler.

The log calls pass `exc_info=exc`. That attaches the traceback of the
exception `handle_error` received. `exc_info=True` reads the exception being
handled at that moment instead, which is empty when the method runs outside
an `except` block, as it does in a test.

### Data errors: route to DLQ

Data errors will never succeed on retry. Protean's `StreamSubscription`
moves messages to DLQ streams (`{stream_category}:dlq`) after exhausting
retries. In `handle_error`, you can alert proactively when you recognize
a data problem:

```python
--8<-- "patterns/classify-async-processing-errors/001.py:data_errors"
```

!!! warning
    Do not silently swallow data errors. DLQ messages that nobody monitors
    are the same as lost messages.

### Logic errors: alert immediately, don't retry

Logic errors are bugs: a projector dividing by zero, a handler assuming a field
that no longer exists. They fail identically on every retry.

```python
--8<-- "patterns/classify-async-processing-errors/001.py:logic_errors"
```

Note the escalation: transient errors log at `WARNING`, data errors at
`ERROR`, logic errors at `CRITICAL`. This maps directly to monitoring
thresholds.

### A reusable error classification mixin

To avoid repeating the classification logic in every handler, extract it
into a mixin:

```python
--8<-- "patterns/classify-async-processing-errors/001.py:mixin"
```

Use it in handlers:

```python
--8<-- "patterns/classify-async-processing-errors/002.py:handler"
```

For projectors, add a subclass that elevates all non-transient errors:

```python
--8<-- "patterns/classify-async-processing-errors/002.py:projector"
```

### Subscribers follow the same pattern

Subscribers that consume messages from external brokers also have
`handle_error`. The same classification applies:

```python
--8<-- "patterns/classify-async-processing-errors/002.py:subscriber_import"
--8<-- "patterns/classify-async-processing-errors/002.py:subscriber"
```

A subscriber's `handle_error` receives the raw broker payload, a `dict`, as
its `message`. The mixin's default hooks do not read the
message, so they work for both. An override on a subscriber that reads
`message.metadata` would fail, so read the payload's keys there instead.

### Using the TraceEmitter

The engine's `TraceEmitter` emits structured trace events to Redis for
every handler exception. The Observatory dashboard tracks these in real
time:

- **`handler.failed`**: Handler name, message ID, stream, duration, error.
- **`message.dlq`**: Emitted when `StreamSubscription` exhausts retries.
- **`message.nacked`**: Emitted on each retry attempt.

Monitor the ratio of `handler.failed` to `handler.completed`. A sudden spike
indicates a systemic problem (deployment bug, infrastructure outage). A
steady trickle indicates data quality issues.

---

## Anti-Patterns

### Silently swallowing errors

```python
# fragment
# WRONG: No handle_error override in production.
@domain.event_handler(part_of=Account)
class AccountEventHandler(BaseEventHandler):

    @handle(AccountCreated)
    def on_account_created(self, event: AccountCreated):
        ...

    # Failures are logged by the engine but nobody is alerted.
```

**Why it's wrong:** If nobody reads the logs, the failure is invisible. The
read model diverges silently.

**Fix:** Always override `handle_error` in production handlers.

### Retrying logic errors

```python
# fragment
# WRONG: Retrying a division by zero will never succeed.
@classmethod
def handle_error(cls, exc: Exception, message: Message) -> None:
    cls._handle(message)  # Same input, same bug
```

**Why it's wrong:** Logic errors are deterministic. Retrying wastes resources
and delays the real fix.

**Fix:** Classify the error first. Only transient errors benefit from retry.

### No monitoring on DLQ depth

```python
# fragment
# WRONG: Messages go to DLQ but nobody checks.
@classmethod
def handle_error(cls, exc: Exception, message: Message) -> None:
    if not _is_transient(exc):
        logger.error("Sending to DLQ: %s", exc)
        # ... but no alert, no metric, no dashboard
```

**Why it's wrong:** a DLQ holds failures, it does not resolve them. Unmonitored DLQ
depth grows silently.

**Fix:** Alert on DLQ depth. Export `message.dlq` trace events to your
monitoring system.

### Catching exceptions inside the handler method

```python
# fragment
# WRONG: Swallowing exceptions inside the handler.
@handle(OrderPlaced)
def on_order_placed(self, event: OrderPlaced):
    try:
        repo = current_domain.repository_for(OrderDashboard)
        repo.add(OrderDashboard(order_id=event.order_id, status="placed"))
    except Exception as exc:
        logger.error("Failed: %s", exc)
        # Swallowed! Engine thinks handler succeeded.
        # handle_error is never called. No retry, no DLQ.
```

**Why it's wrong:** The engine emits `handler.completed` instead of
`handler.failed`. The `handle_error` hook is never invoked. The message is
acknowledged and lost.

**Fix:** Let exceptions propagate. The engine's error pipeline (log, trace,
`handle_error`, continue) is designed to catch them.

### Custom retry logic in handle_error

```python
# fragment
# WRONG: Rolling your own retry loop.
@classmethod
def handle_error(cls, exc: Exception, message: Message) -> None:
    for attempt in range(3):
        try:
            time.sleep(2 ** attempt)
            cls._handle(message)
            return
        except Exception:
            continue
```

**Why it's wrong:** The subscription already retries failed messages, and
`transient_retry` retries transient failures with exponential backoff. A
custom retry loop blocks the engine's event loop and bypasses the
`TraceEmitter`.

**Fix:** Trust the framework's retry infrastructure. Configure `max_retries`
on the subscription, or turn on `transient_retry`, instead.

---

## Summary

| Error Category | Recognition | Strategy | Retry helps? | Alert Level |
|---------------|-------------|----------|--------|-------------|
| **Transient** | `ConnectionError`, `TimeoutError`, deadlock messages | Let the framework retry the message | Yes | `WARNING` |
| **Data error** | `KeyError`, `TypeError`, schema/deserialization messages | Route to DLQ, alert team | No | `ERROR` |
| **Logic error** | Everything else (bugs, unexpected `None`, wrong calculations) | Alert immediately, fix code, replay from event store | No | `CRITICAL` |

The default `handle_error` is a no-op by design. It keeps the engine running.
In production, override it in every handler to classify failures, route to the
right recovery path, and ensure that no error goes unnoticed. Transient errors
heal themselves. Data errors need human inspection. Logic errors need code
fixes. Treating them all the same way produces silent data drift.

---

!!! tip "Related reading"
    **Patterns:**

    - [Idempotent Event Handlers](idempotent-event-handlers.md): Safe replay when retrying.
    - [Message Tracing](message-tracing.md): Correlation and causation IDs for debugging failed handlers.

    **Concepts:**

    - [Engine](../concepts/async-processing/engine.md): How the async processing engine works.
    - [Outbox](../concepts/async-processing/outbox.md): Reliable message delivery with retry.

    **Guides:**

    - [Event Handlers](../guides/consume-state/event-handlers.md): Defining and configuring event handlers.
