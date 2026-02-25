# Chapter 20: Orchestrating Multi-Step Workflows — Process Managers

Order fulfillment in a real bookstore is a multi-step process: confirm
the order, reserve inventory, arrange shipping. If shipping fails
(invalid address), the inventory reservation must be reversed. This is a
long-running workflow that spans multiple aggregates and must handle
failures gracefully.

A **domain service** (Chapter 13) handles synchronous, single-step
cross-aggregate validation. A **process manager** handles asynchronous,
multi-step workflows with compensation logic.

### Domain Service vs. Process Manager

| | Domain Service | Process Manager |
|---|---------------|----------------|
| **When** | Synchronous, same transaction | Asynchronous, across multiple transactions |
| **State** | Stateless | Stateful — remembers what happened so far |
| **Failure** | Rolls back the transaction | Issues compensating commands |
| **Use case** | "Check inventory before confirming" | "Confirm → reserve → ship → complete" |

## The Shipping Aggregate

First, we need a Shipping aggregate to represent shipments:

```python
--8<-- "guides/getting-started/tutorial/ch20.py:shipping"
```

The `create_shipment` method validates the address and raises either
`ShipmentCreated` or `ShipmentFailed`. This is important — the process
manager reacts to these events to decide the next step.

## The Process Manager

The `OrderFulfillmentPM` coordinates the fulfillment workflow:

```python
--8<-- "guides/getting-started/tutorial/ch20.py:process_manager"
```

### Key Concepts

**`stream_categories`** — The process manager subscribes to events from
the `order`, `inventory`, and `shipment` streams. It sees all events
from these three aggregates.

**`order_id` field** — Process managers are stateful. The `order_id`
field is persisted between events, so the PM remembers which order it
is tracking across the entire workflow.

**`start=True`** — The `on_order_confirmed` handler is marked as the
start event. When an `OrderConfirmed` event arrives, Protean creates
a *new* PM instance and stores the correlated `order_id`.

**`correlate`** — Each handler declares how to match incoming events to
existing PM instances:

- `correlate="order_id"` — The event's `order_id` field matches the PM's
  `order_id` field directly.
- `correlate={"order_id": "book_id"}` — Maps the PM's `order_id` to the
  event's `book_id` field (for events that don't carry `order_id`).

**`mark_as_complete()`** — Marks the PM instance as finished. Subsequent
events for this `order_id` are skipped.

### How It Works

1. **`OrderConfirmed`** fires → PM starts (via `start=True`), issues
   `ReserveInventory` command.
2. **`InventoryReserved`** fires → PM issues `CreateShipment` command.
3. **`ShipmentCreated`** fires → PM issues `CompleteOrder` command,
   marks itself complete.
4. **`ShipmentFailed`** fires → PM issues `ReleaseInventory` and
   `CancelOrder` commands (compensation).

## The Compensation Pattern

When `ShipmentFailed` fires, the PM must undo the reservation:

```
OrderConfirmed ──► ReserveInventory ──► CreateShipment
                                              │
                                       ShipmentFailed
                                              │
                                  ┌───────────┴───────────┐
                                  ▼                       ▼
                          ReleaseInventory          CancelOrder
```

This is the **saga pattern** — each step has a compensating action that
undoes it if a subsequent step fails. The process manager is the
coordinator that decides when to compensate.

Design compensating actions to be **idempotent** — if `ReleaseInventory`
is processed twice (e.g., due to a retry), the second invocation should
be harmless. This is critical for reliability in asynchronous systems.

## Testing the Process Manager

```python
--8<-- "guides/getting-started/tutorial/ch20.py:tests"
```

Process managers are best tested through integration tests that verify
the full event chain. In sync processing mode
(`domain.config["event_processing"] = "sync"`), events are processed
immediately, making it straightforward to assert the final state after
triggering the initial event.

## What We Built

- A **Shipping aggregate** representing shipments with success and
  failure outcomes.
- An **`OrderFulfillmentPM` process manager** that coordinates
  fulfillment across Order, Inventory, and Shipping.
- **Event correlation** using `correlate` to route events to the
  correct PM instance.
- **Compensation logic** that reverses reservations when shipping fails.
- The **saga pattern** for long-running, multi-aggregate workflows.

In the next chapter, we will explore advanced query patterns for
building a rich storefront.

## Full Source

```python
--8<-- "guides/getting-started/tutorial/ch20.py:full"
```

## Next

[Chapter 21: Advanced Query Patterns →](21-query-patterns.md)
