# Chapter 20: Orchestrating Multi-Step Workflows — Process Managers

Order fulfillment in a real bookstore is a multi-step process: confirm
the order, reserve inventory, arrange shipping. If shipping fails
(invalid address), the inventory reservation must be reversed. This is a
long-running workflow that spans multiple aggregates and must handle
failures gracefully.

A **domain service** (Chapter 13) handles synchronous, single-step
cross-aggregate validation. A **process manager** handles asynchronous,
multi-step workflows with compensation logic.

## The Shipping Aggregate

First, we need a Shipping aggregate to represent shipments:

```python
--8<-- "guides/getting-started/tutorial/ch20.py:shipping"
```

## The Process Manager

The `OrderFulfillmentPM` coordinates the fulfillment workflow:

```python
--8<-- "guides/getting-started/tutorial/ch20.py:process_manager"
```

### How It Works

1. **`OrderConfirmed`** fires → PM starts (via `start=True`), issues
   `ReserveInventory` command.
2. **`InventoryReserved`** fires → PM issues `CreateShipment` command.
3. **`ShipmentCreated`** fires → PM issues `CompleteOrder` command,
   marks itself complete.
4. **`ShipmentFailed`** fires → PM issues `ReleaseInventory` and
   `CancelOrder` commands (compensation).

The `correlate="order_id"` parameter links all events to the same PM
instance, so the PM maintains state across the workflow.

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
undoes it if a subsequent step fails.

## Testing the Process Manager

```python
--8<-- "guides/getting-started/tutorial/ch20.py:tests"
```

## What We Built

- A **Shipping aggregate** representing shipments.
- An **`OrderFulfillmentPM` process manager** that coordinates
  fulfillment across Order, Inventory, and Shipping.
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
