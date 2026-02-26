# Classify and Handle Async Processing Errors

## The Problem

An e-commerce platform uses a projector to maintain an `OrderDashboard`
projection:

```python
@domain.projector(projector_for=OrderDashboard, aggregates=[Order])
class OrderDashboardProjector(BaseProjector):

    @on(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(OrderDashboard)
        repo.add(OrderDashboard(
            order_id=event.order_id,
            customer_name=event.customer_name,
            status="placed",
            total=event.total,
        ))

    @on(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        repo = current_domain.repository_for(OrderDashboard)
        dashboard = repo.get(event.order_id)
        dashboard.status = "shipped"
        dashboard.shipped_at = event.shipped_at
        repo.add(dashboard)
```

On Tuesday, the Elasticsearch cluster is temporarily unreachable. The
projector fails on an `OrderShipped` event with a connection timeout. The
engine logs the exception, calls the default (no-op) `handle_error`, and
moves on. The order stays stuck at "placed" in the dashboard while the write
side has already moved to "shipped".

Nobody notices. There are no alerts, no DLQ entries, no metrics spike.

On Thursday, a developer deploys a new event version that adds a `currency`
field to `OrderPlaced`. The projector has not been updated. Every new order
fails with a schema mismatch -- but the team only monitors HTTP error rates.
Async handler failures are invisible.

By Friday, the read model is 72 hours behind the write model. Customer
support is working from wrong data.

This is not exotic. It is the *default behavior* of any async pipeline that
logs errors and continues. The Protean engine is resilient -- it never
crashes on a handler exception -- but resilience without observability is
silent data drift.

The root causes are different in kind:

- The Elasticsearch timeout is **transient**. Retrying would succeed.
- The schema mismatch is a **data error**. Retrying will never fix it.
- A bug in the projector's logic is a **logic error**. It needs a code fix,
  not a retry.

Treating all three the same way -- log and continue -- is the real problem.

---

## The Pattern

Override `handle_error()` in every production handler. Classify each failure
into one of three categories and respond accordingly:

| Category | Examples | Strategy |
|----------|----------|----------|
| **Transient** | Network timeouts, lock contention, broker unavailability | Let the outbox retry with exponential backoff |
| **Data error** | Schema mismatch, missing fields, invalid payload | Route to DLQ for manual inspection, alert the team |
| **Logic error** | Business rule violations, incorrect calculations, unexpected `None` | Alert immediately, don't retry, fix the code, replay |

The mental model:

```
Exception raised in handler
    |
    +-- Is it transient?
    |       Yes --> Log WARNING, let outbox retry handle it.
    |
    +-- Is it a data problem?
    |       Yes --> Send to DLQ. Alert the team.
    |
    +-- Is it a logic bug?
            Yes --> Alert immediately. Fix the code. Replay.
```

### Why this matters for projectors

Projectors maintain read models. A failed projector update means the read
side has diverged from the write side. Unlike a failed event handler -- where
the consequence might be a delayed side effect -- a failed projector creates
**stale data that users see**. This makes projector error handling especially
critical: a transient failure should retry quickly, a persistent failure
should alert immediately.

### The `handle_error` contract

Protean's `HandlerMixin` provides a `handle_error` classmethod that the
engine calls whenever a handler raises an exception:

```python
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
4. `handler_cls.handle_error(exc, message)` is called inside a `try/except`
   -- if *it* also fails, that secondary exception is logged but does not
   crash the engine.
5. Processing continues with the next message.

This means `handle_error` is your **classification hook**. It runs after the
failure is already recorded in traces and logs. Its job is to decide what
happens next: nothing (for transient errors the outbox will retry), DLQ
routing, or immediate alerting.

---

## Applying the Pattern

### Classifying errors

Build helpers that recognize common failure signatures:

```python
import socket

TRANSIENT_EXCEPTION_TYPES = (
    ConnectionError,
    TimeoutError,
    socket.timeout,
    OSError,
)

TRANSIENT_PATTERNS = (
    "deadlock",
    "lock timeout",
    "connection reset",
    "too many connections",
)

DATA_ERROR_TYPES = (
    KeyError,
    TypeError,
    ValueError,
)

DATA_ERROR_PATTERNS = (
    "missing required field",
    "invalid type",
    "schema",
    "deserialization",
)


def _is_transient(exc: Exception) -> bool:
    """Determine if an exception is transient and likely to succeed on retry."""
    if isinstance(exc, TRANSIENT_EXCEPTION_TYPES):
        return True
    msg = str(exc).lower()
    return any(p in msg for p in TRANSIENT_PATTERNS)


def _is_data_error(exc: Exception) -> bool:
    """Determine if an exception is caused by bad message data."""
    if isinstance(exc, DATA_ERROR_TYPES):
        return True
    msg = str(exc).lower()
    return any(p in msg for p in DATA_ERROR_PATTERNS)
```

!!! note
    This classification is domain-specific. If your projection store is
    Elasticsearch, add `ConnectionTimeout` and `TransportError` to the
    transient list. If you use a third-party API, add its rate-limit
    and gateway-timeout exceptions.

### Transient errors: let the outbox retry

Transient errors resolve themselves. The outbox already implements
exponential backoff: `delay = min(base_delay * 2^retry_count, max_backoff)`.
After `max_retries`, the status becomes `ABANDONED`.

For transient errors, the best action in `handle_error` is minimal logging:

```python
@domain.event_handler(part_of=Inventory)
class InventoryEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def reserve_inventory(self, event: OrderPlaced):
        repo = current_domain.repository_for(Inventory)
        for item in event.items:
            inventory = repo.get(item["product_id"])
            inventory.reserve(
                order_id=event.order_id,
                quantity=item["quantity"],
            )
            repo.add(inventory)

    @classmethod
    def handle_error(cls, exc: Exception, message: Message) -> None:
        if _is_transient(exc):
            logger.warning(
                "Transient error in %s, will retry: %s",
                cls.__name__, exc,
            )
            return

        if _is_data_error(exc):
            logger.error(
                "Data error in %s, message_id=%s: %s",
                cls.__name__,
                message.metadata.headers.id if message.metadata else "unknown",
                exc, exc_info=True,
            )
            _alert_data_error(cls.__name__, exc, message)
            return

        # Logic error: alert immediately
        logger.critical(
            "Logic error in %s, message_id=%s: %s",
            cls.__name__,
            message.metadata.headers.id if message.metadata else "unknown",
            exc, exc_info=True,
        )
        _alert_logic_error(cls.__name__, exc, message)
```

### Data errors: route to DLQ

Data errors will never succeed on retry. Protean's `StreamSubscription`
moves messages to DLQ streams (`{stream_category}:dlq`) after exhausting
retries. In `handle_error`, you can alert proactively when you recognize
a data problem:

```python
@domain.event_handler(part_of=Shipping)
class ShippingEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def create_shipment(self, event: OrderPlaced):
        repo = current_domain.repository_for(Shipment)
        repo.add(Shipment(
            order_id=event.order_id,
            customer_id=event.customer_id,
            items=event.items,
            status="pending",
        ))

    @classmethod
    def handle_error(cls, exc: Exception, message: Message) -> None:
        if _is_transient(exc):
            logger.warning("Transient error in %s: %s", cls.__name__, exc)
            return

        if _is_data_error(exc):
            logger.error(
                "Data error in %s -- message will move to DLQ. "
                "message_id=%s, type=%s, error=%s",
                cls.__name__,
                message.metadata.headers.id if message.metadata else "unknown",
                message.metadata.headers.type if message.metadata else "unknown",
                exc, exc_info=True,
            )
            _alert_data_error(cls.__name__, exc, message)
            return

        _alert_logic_error(cls.__name__, exc, message)
```

!!! warning
    Do not silently swallow data errors. DLQ messages that nobody monitors
    are the same as lost messages.

### Logic errors: alert immediately, don't retry

Logic errors are bugs -- a projector dividing by zero, a handler assuming
a field that no longer exists. They fail identically on every retry.

```python
@domain.projector(projector_for=OrderDashboard, aggregates=[Order])
class OrderDashboardProjector(BaseProjector):

    @on(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(OrderDashboard)
        repo.add(OrderDashboard(
            order_id=event.order_id,
            customer_name=event.customer_name,
            status="placed",
            total=event.total,
        ))

    @on(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        repo = current_domain.repository_for(OrderDashboard)
        dashboard = repo.get(event.order_id)
        dashboard.status = "shipped"
        dashboard.shipped_at = event.shipped_at
        repo.add(dashboard)

    @classmethod
    def handle_error(cls, exc: Exception, message: Message) -> None:
        if _is_transient(exc):
            logger.warning(
                "Transient error in %s (projection may be stale): %s",
                cls.__name__, exc,
            )
            return

        # For projectors, any non-transient error means a stale read model
        logger.critical(
            "%s in %s -- projection is stale. message_id=%s, error=%s",
            "Data error" if _is_data_error(exc) else "Logic error (BUG)",
            cls.__name__,
            message.metadata.headers.id if message.metadata else "unknown",
            exc, exc_info=True,
        )
        _alert_stale_projection(cls.__name__, exc, message)
```

Note the escalation: transient errors log at `WARNING`, data errors at
`ERROR`, logic errors at `CRITICAL`. This maps directly to monitoring
thresholds.

### A reusable error classification mixin

To avoid repeating the classification logic in every handler, extract it
into a mixin:

```python
class ErrorClassificationMixin:
    """Classifies handler exceptions into transient, data, and logic errors.

    Subclasses override ``on_transient_error``, ``on_data_error``, or
    ``on_logic_error`` to customize behavior per handler.
    """

    _extra_transient_types: tuple = ()
    _extra_data_error_types: tuple = ()

    @classmethod
    def handle_error(cls, exc: Exception, message: Message) -> None:
        if cls._classify_transient(exc):
            cls.on_transient_error(exc, message)
        elif cls._classify_data_error(exc):
            cls.on_data_error(exc, message)
        else:
            cls.on_logic_error(exc, message)

    @classmethod
    def _classify_transient(cls, exc: Exception) -> bool:
        types = TRANSIENT_EXCEPTION_TYPES + cls._extra_transient_types
        if isinstance(exc, types):
            return True
        msg = str(exc).lower()
        return any(p in msg for p in TRANSIENT_PATTERNS)

    @classmethod
    def _classify_data_error(cls, exc: Exception) -> bool:
        types = DATA_ERROR_TYPES + cls._extra_data_error_types
        if isinstance(exc, types):
            return True
        msg = str(exc).lower()
        return any(p in msg for p in DATA_ERROR_PATTERNS)

    @classmethod
    def on_transient_error(cls, exc: Exception, message: Message) -> None:
        logger.warning("Transient error in %s: %s", cls.__name__, exc)

    @classmethod
    def on_data_error(cls, exc: Exception, message: Message) -> None:
        logger.error("Data error in %s: %s", cls.__name__, exc, exc_info=True)

    @classmethod
    def on_logic_error(cls, exc: Exception, message: Message) -> None:
        logger.critical("Logic error in %s: %s", cls.__name__, exc, exc_info=True)
```

Use it in handlers:

```python
@domain.event_handler(part_of=Inventory)
class InventoryEventHandler(ErrorClassificationMixin, BaseEventHandler):

    @handle(OrderPlaced)
    def reserve_inventory(self, event: OrderPlaced):
        repo = current_domain.repository_for(Inventory)
        for item in event.items:
            inventory = repo.get(item["product_id"])
            inventory.reserve(order_id=event.order_id, quantity=item["quantity"])
            repo.add(inventory)

    @classmethod
    def on_logic_error(cls, exc: Exception, message: Message) -> None:
        super().on_logic_error(exc, message)
        pagerduty.trigger(
            summary=f"Logic error in {cls.__name__}: {exc}",
            severity="critical",
        )
```

For projectors, add a subclass that elevates all non-transient errors:

```python
class ProjectorErrorMixin(ErrorClassificationMixin):
    """Elevated alerting for projector failures -- any non-transient error
    means the read model is stale and users see wrong data."""

    @classmethod
    def on_data_error(cls, exc: Exception, message: Message) -> None:
        super().on_data_error(exc, message)
        _alert_stale_projection(cls.__name__, exc, message)

    @classmethod
    def on_logic_error(cls, exc: Exception, message: Message) -> None:
        super().on_logic_error(exc, message)
        _alert_stale_projection(cls.__name__, exc, message)


@domain.projector(projector_for=OrderDashboard, aggregates=[Order])
class OrderDashboardProjector(ProjectorErrorMixin, BaseProjector):

    @on(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(OrderDashboard)
        repo.add(OrderDashboard(
            order_id=event.order_id,
            status="placed",
            total=event.total,
        ))
```

### Subscribers follow the same pattern

Subscribers that consume messages from external brokers also have
`handle_error`. The same classification applies:

```python
@domain.subscriber(stream="payments::completed")
class PaymentCompletedSubscriber(ErrorClassificationMixin, BaseSubscriber):

    def __call__(self, payload: dict) -> None:
        current_domain.process(
            MarkOrderPaid(order_id=payload["order_id"], amount=payload["amount"])
        )
```

### Leveraging the TraceEmitter

The engine's `TraceEmitter` emits structured trace events to Redis for
every handler exception. The Observatory dashboard tracks these in real
time:

- **`handler.failed`** -- handler name, message ID, stream, duration, error.
- **`message.dlq`** -- emitted when `StreamSubscription` exhausts retries.
- **`message.nacked`** -- emitted on each retry attempt.

Monitor the ratio of `handler.failed` to `handler.completed`. A sudden spike
indicates a systemic problem (deployment bug, infrastructure outage). A
steady trickle indicates data quality issues.

---

## Anti-Patterns

### Silently swallowing errors

```python
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
# WRONG: Messages go to DLQ but nobody checks.
@classmethod
def handle_error(cls, exc: Exception, message: Message) -> None:
    if not _is_transient(exc):
        logger.error("Sending to DLQ: %s", exc)
        # ... but no alert, no metric, no dashboard
```

**Why it's wrong:** DLQ is a parking lot, not a solution. Unmonitored DLQ
depth grows silently.

**Fix:** Alert on DLQ depth. Export `message.dlq` trace events to your
monitoring system.

### Catching exceptions inside the handler method

```python
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

**Why it's wrong:** The outbox and `StreamSubscription` already implement
retry with exponential backoff. A custom retry loop blocks the engine's
event loop and bypasses the `TraceEmitter`.

**Fix:** Trust the framework's retry infrastructure. Configure `max_retries`
on the outbox or subscription instead.

---

## Summary

| Error Category | Recognition | Strategy | Retry? | Alert Level |
|---------------|-------------|----------|--------|-------------|
| **Transient** | `ConnectionError`, `TimeoutError`, deadlock messages | Let outbox retry with exponential backoff | Yes (automatic) | `WARNING` |
| **Data error** | `KeyError`, `TypeError`, schema/deserialization messages | Route to DLQ, alert team | No | `ERROR` |
| **Logic error** | Everything else (bugs, unexpected `None`, wrong calculations) | Alert immediately, fix code, replay from event store | No | `CRITICAL` |

The principle: **the default `handle_error` is a no-op by design -- it keeps
the engine running. In production, override it in every handler to classify
failures, route to the right recovery path, and ensure that no error goes
unnoticed. Transient errors heal themselves. Data errors need human
inspection. Logic errors need code fixes. Treating them all the same way
produces silent data drift.**

---

!!! tip "Related reading"
    **Patterns:**

    - [Idempotent Event Handlers](idempotent-event-handlers.md) -- Safe replay when retrying.
    - [Message Tracing](message-tracing.md) -- Correlation and causation IDs for debugging failed handlers.

    **Concepts:**

    - [Engine](../concepts/async-processing/engine.md) -- How the async processing engine works.
    - [Outbox](../concepts/async-processing/outbox.md) -- Reliable message delivery with retry.

    **Guides:**

    - [Event Handlers](../guides/consume-state/event-handlers.md) -- Defining and configuring event handlers.
