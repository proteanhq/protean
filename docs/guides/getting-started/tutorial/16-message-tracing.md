# Chapter 16: Following the Trail — Message Tracing

A customer reports that their order was confirmed but inventory was
never updated. The support team needs to trace what happened: did the
command arrive? Did the event fire? Did the handler run? Where did the
chain break?

## Correlation and Causation

Every message in Protean carries two tracing identifiers:

- **Correlation ID** — shared by all messages in the same causal chain.
  When you dispatch a command with a correlation ID, every event and
  handler invocation in the chain inherits it.
- **Causation ID** — points to the immediate parent message. If Event B
  was caused by Command A, then B's causation ID is A's message ID.

Together, they form a tree:

```
AddBook (command)         ← correlation_id = "abc-123"
  └─ BookAdded (event)   ← causation_id = AddBook.id
       ├─ Inventory created (handler)
       └─ Catalog updated (projector)
```

## Setting Correlation IDs

Pass a `correlation_id` when dispatching commands to make tracing
easier:

```python
import uuid

trace_id = str(uuid.uuid4())
domain.process(
    AddBook(title="Dune", author="Frank Herbert", price_amount=15.99),
    correlation_id=trace_id,
)
```

All downstream events and handler invocations inherit this correlation
ID automatically.

## Tracing with the CLI

Use the `protean events trace` command to visualize the causal chain:

```shell
$ protean events trace --domain bookshelf --correlation-id abc-123
Trace for correlation abc-123:
  ├─ AddBook (command) → BookCommandHandler
  │   ├─ BookAdded (event) → BookEventHandler
  │   │   └─ Inventory created
  │   └─ BookAdded (event) → BookCatalogProjector
  │       └─ BookCatalog updated
  └─ Complete ✓
```

If the chain is broken (a handler failed or didn't run), the trace
shows where the gap is.

## Programmatic Tracing

You can also trace programmatically:

```python
from protean.utils.globals import current_domain

# Get all events for a correlation ID
events = current_domain.event_store.events_of(
    correlation_id="abc-123"
)
for event in events:
    print(f"{event.__class__.__name__} caused by {event._metadata.causation_id}")
```

## Debugging the Customer's Issue

Armed with the order's correlation ID, the support team can:

1. Find the `ConfirmOrder` command in the trace.
2. See if it produced an `OrderConfirmed` event.
3. Check if the `OrderEventHandler` processed it.
4. Identify the exact point of failure.

## What We Built

- Understanding of **correlation IDs** and **causation IDs**.
- Using `protean events trace` to visualize causal chains.
- A debugging workflow for tracing production issues.

In the next chapter, we will handle the case where a handler fails
entirely — dead-letter queue management.

## Next

[Chapter 17: When Things Go Wrong — Dead Letter Queues →](17-dead-letter-queues.md)
