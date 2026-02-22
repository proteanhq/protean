# Message Tracing in Event-Driven Systems

In event-driven architectures, a single user action often triggers a cascade of
commands and events across multiple aggregates and services. Without tracing,
debugging a production issue means manually piecing together log entries,
database records, and event store messages. Two simple metadata fields --
`correlation_id` and `causation_id` -- solve this by threading through every
message in the chain.

## The Problem

Consider an e-commerce checkout: placing an order triggers payment processing,
inventory reservation, and shipping notification. If the shipping notification
fails, you need to answer:

1. **Which user request caused this?** (correlation)
2. **What was the immediate trigger?** (causation)
3. **What other effects did that request produce?** (chain traversal)

Without explicit tracing, the only clue is `origin_stream` -- a single string
recording where a command came from. That tells you the source aggregate but
not the full chain.

## The Pattern

Attach two identifiers to every command and event:

- **`correlation_id`**: Constant across the entire causal chain. Generated at
  the earliest entry point (often the API gateway or frontend) and carried
  through every subsequent message. All messages belonging to the same business
  operation share one `correlation_id`.

- **`causation_id`**: Points to the immediate parent. When a command handler
  raises an event, the event's `causation_id` is the command's message ID.
  When an event handler dispatches a new command, the command's `causation_id`
  is the event's message ID.

Together, they form a **causation tree**:

```
PlaceOrder [corr=X, cause=None]              <-- root command
  +-- OrderPlaced [corr=X, cause=PlaceOrder.id]
        +-- ReserveInventory [corr=X, cause=OrderPlaced.id]
        |     +-- InventoryReserved [corr=X, cause=ReserveInventory.id]
        +-- NotifyCustomer [corr=X, cause=OrderPlaced.id]
              +-- NotificationSent [corr=X, cause=NotifyCustomer.id]
```

## Design Decisions

### Where to Generate correlation_id

The `correlation_id` should be generated as early as possible -- ideally by the
caller (API gateway, frontend, CLI). This lets you trace a request from the
moment it enters the system:

```python
# In your FastAPI endpoint
@router.post("/orders")
async def place_order(request: PlaceOrderRequest):
    correlation_id = request.headers.get(
        "X-Correlation-ID",
        uuid4().hex,  # Fallback: generate at the API boundary
    )
    domain.process(
        PlaceOrder(**request.dict()),
        correlation_id=correlation_id,
    )
```

If no external `correlation_id` is provided, Protean generates one
automatically when `domain.process()` is called. This means every message
chain always has a `correlation_id` -- you never have to check for `None`.

### Format: Flexible Strings, Not UUIDs

The `correlation_id` is a flexible string, not strictly a UUID. It can be:

- A UUID4 hex (`a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6`) -- Protean's default
- A request ID from an API gateway (`req-abc-123-def`)
- A trace ID from an external tracing system (`00-4bf92f3577b34da6a3ce929d0e0e4736-...`)

This flexibility lets you integrate with existing infrastructure without
reformatting IDs.

The `causation_id` is always a Protean message ID (e.g.,
`myapp::order-abc123-0.1`), which is intentionally human-readable for
debugging.

### Separation from W3C TraceParent

Protean supports W3C `TraceParent` in `MessageHeaders.traceparent` for
integration with distributed tracing tools (Jaeger, Zipkin, Datadog). The
domain-level `correlation_id` and `causation_id` serve a different purpose:

| Concern | Domain tracing | Distributed tracing |
|---------|---------------|-------------------|
| **Location** | `DomainMeta.correlation_id` / `causation_id` | `MessageHeaders.traceparent` |
| **Purpose** | Business operation tracking | Infrastructure span tracking |
| **Format** | Flexible strings | W3C 32-hex / 16-hex |
| **Required** | Always present | Optional integration |

The `correlation_id` bridges both layers -- it identifies the same operation.
But `causation_id` cannot live in `TraceParent.parent_id` because Protean's
message IDs are human-readable strings, not 16-hex-char span IDs.

## Protean's Implementation

Protean implements this pattern automatically. No opt-in required.

### Automatic Propagation

Trace context flows through all message construction paths via
`g.message_in_context`:

1. **`domain.process(command)`** -- Generates or accepts `correlation_id`,
   sets `causation_id = None` (root command)
2. **Command handler raises events** -- Events inherit `correlation_id` from
   the command, `causation_id` = command's `headers.id`
3. **Event handler dispatches commands** -- New commands inherit
   `correlation_id` from the event, `causation_id` = event's `headers.id`

This works in both sync and async processing modes.

### Outbox Denormalization

The outbox stores `correlation_id` and `causation_id` as indexed columns
alongside the full message metadata. This enables efficient queries:

```python
# Find all messages from a business operation
outbox_repo.find_by_correlation_id("a1b2c3d4...")

# Find all messages caused by a specific parent
outbox_repo.find_by_causation_id("myapp::order-abc123-0.1")
```

### CLI Inspection

The `protean events` CLI supports tracing:

```bash
# Show trace IDs alongside events
protean events read "myapp::order-abc123" --trace

# Follow a full causal chain
protean events trace "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
```

## When to Use External Correlation IDs

**Always prefer external IDs when available.** If your API gateway or frontend
generates request IDs, pass them through as `correlation_id`. This gives you
end-to-end traceability from the user's browser to the last event handler.

Generate IDs at the Protean boundary only when:

- The entry point is a scheduled job or cron task
- The message originates from an external system that doesn't provide trace IDs
- You're in development/testing and don't have an API gateway

## Multi-Service Tracing

When one Protean service consumes events from another (via subscribers), the
`correlation_id` from the source event should be forwarded:

```python
@domain.subscriber(channel="payments")
class PaymentSubscriber:
    def __call__(self, message):
        # Extract correlation_id from the incoming external event
        correlation_id = message.get("metadata", {}).get("correlation_id")

        domain.process(
            ConfirmPayment(order_id=message["order_id"]),
            correlation_id=correlation_id,
        )
```

This stitches the causal chain across service boundaries.

## Testing Trace Propagation

Protean's test DSL supports explicit correlation IDs:

```python
from protean.testing import given

result = (
    given(Order)
    .when(PlaceOrder(customer_id="cust-1", items=[...]))
    .then_events(OrderPlaced)
)

# Verify correlation_id was generated
corr_id = result.events[0]._metadata.domain.correlation_id
assert corr_id is not None
assert len(corr_id) == 32  # UUID4 hex

# Verify causation chain
assert result.events[0]._metadata.domain.causation_id is not None
```

For multi-step chains, forward the correlation ID explicitly:

```python
result2 = result.process(
    ReserveInventory(order_id=result.aggregate.id),
    correlation_id=corr_id,
)

# Same correlation_id, different causation_id
assert result2.events[0]._metadata.domain.correlation_id == corr_id
```

## Key Takeaways

- **`correlation_id`** groups all messages from one business operation.
  Generate early, propagate everywhere.
- **`causation_id`** links each message to its direct parent, forming a tree.
- Protean handles propagation automatically -- you only need to supply an
  external `correlation_id` at the entry point if you have one.
- Use `protean events trace` to follow a full chain in the event store.
- Prefer external (caller-provided) correlation IDs for end-to-end
  traceability across services.

---

!!! tip "See also"
    **Guide:** [Message Tracing](../guides/domain-behavior/message-tracing.md) -- How-to guide with code examples for setting up tracing.

    **Reference:** [`protean events trace`](../reference/cli/data/events.md) -- CLI command for following causal chains.

    **Related patterns:**

    - [Coordinating Long-Running Processes](coordinating-long-running-processes.md) -- Process managers use correlation to track multi-step workflows.
    - [Consuming Events from Other Domains](consuming-events-from-other-domains.md) -- Subscribers as anti-corruption layers, where correlation IDs bridge services.
