# Chapter 20: Orchestrating Multi-Step Workflows with Process Managers

Order fulfillment in a real bookstore is a multi-step process: confirm
the order, reserve inventory, arrange shipping. If shipping fails
(invalid address), the inventory reservation must be reversed. This is a
long-running workflow that spans multiple aggregates and must handle
failures gracefully.

A **domain service** (Chapter 13) handles synchronous, single-step
cross-aggregate validation: it checks the rule before one aggregate changes.
A **process manager** handles asynchronous, multi-step workflows with
compensation logic.

### Domain Service vs. Process Manager

| | Domain Service | Process Manager |
|---|---------------|----------------|
| **When** | Synchronous, before the one aggregate the command changes | Asynchronous, across multiple transactions |
| **State** | Stateless | Stateful, remembers what happened so far |
| **Failure** | Rejects the command, so nothing is saved | Issues compensating commands |
| **Use case** | "Check inventory before confirming" | "Confirm → reserve → ship → complete" |

## The Shipping Aggregate

First, we need a Shipping aggregate to represent shipments:

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch20.py:shipping"
```

The `create_shipment` method validates the address and raises either
`ShipmentCreated` or `ShipmentFailed`. This is important, the process manager
reacts to these events to decide the next step.

## The Process Manager

In Chapter 13, the `reserve_inventory` method on `OrderEventHandler` sent a
`ReserveInventory` command for each title in `OrderConfirmed`. The process
manager now sends those commands, so remove `reserve_inventory` from
`OrderEventHandler`. Then one place starts the reservation: the process
manager, which also releases the stock if a later step fails. If both stay,
Inventory's command handler finds the order in `reserved_order_ids` and skips
the second command, so the stock is still reserved once.
`OrderConfirmed` and `ReserveInventory` stay as Chapter 13 defined them.
`Inventory.reserve()` now also raises `InventoryReserved`, which tells the
process manager a title is reserved, and records the quantity it took for the
order in `reserved_quantities`. Inventory's command handler also skips an order
in `released_order_ids`, so a reservation that arrives after compensation has
released the order takes no stock.

The `OrderFulfillmentPM` coordinates the fulfillment workflow:

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch20.py:process_manager"
```

### Key Concepts

**`stream_categories`**, The process manager subscribes to events from the `order`, `inventory`, and `shipment`
streams. It sees all events from these three aggregates.

**`order_id`, `items` and `awaiting_titles` fields**, Process managers are
stateful. These fields are saved between events. `order_id` says which order
the PM is tracking. `items` keeps the titles and quantities, so the PM knows
what to release if shipping fails. `awaiting_titles` lists the titles not yet
reserved, so the PM creates the shipment only after the last one. An
`InventoryReserved` for a title no longer in the list is a repeat, and the PM
ignores it. Shipment's command handler also skips an order that already has a
shipment.

**`start=True`**, The `on_order_confirmed` handler is marked as the start event. When an `OrderConfirmed` event
arrives, Protean creates a *new* PM instance and stores the correlated `order_id`.

**`correlate`**, Each handler declares how to match incoming events to existing PM
instances:

- `correlate="order_id"`: Protean reads the event's `order_id` value and
  routes the event to the PM instance started with that value. Every event in
  this workflow carries the order's id, which is why `InventoryReserved` has an
  `order_id` field.
- When an event carries the order's id under another name, use a dictionary,
  such as `correlate={"order_id": "order_ref"}`. Protean reads `event.order_ref`
  and matches its value the same way.

**`end=True`**, Marks the PM instance as finished once the handler returns.
Subsequent events for this `order_id` are skipped. Both the success handler and
the compensation handler end the workflow.

### How It Works

1. **`OrderConfirmed`** fires → PM starts (via `start=True`), issues one
   `ReserveInventory` command per title.
2. **`InventoryReserved`** fires for each title → once every title is
   reserved, PM issues `CreateShipment` command.
3. **`ShipmentCreated`** fires → PM issues `CompleteOrder` command and
   completes (`end=True`).
4. **`ShipmentFailed`** fires → PM issues `ReleaseInventory` and
   `CancelOrder` commands (compensation) and completes (`end=True`).

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

The PM sends one `ReleaseInventory` per title. The command carries no
quantity: Inventory returns the quantity it recorded for the order when it
reserved.

This chapter compensates a failed shipment only. If a reservation fails because
another order took the last copies, `Inventory.reserve()` raises
`ValidationError` and the order stays `CONFIRMED`. Handling that takes a
`ReservationFailed` event in place of the error, and a PM handler that releases
the titles already reserved and cancels the order, as `on_shipment_failed`
does.

This is the **saga pattern**. Each step has a compensating action that undoes
it if a subsequent step fails. The process manager is the coordinator that
decides when to compensate.

Design compensating actions to be **idempotent**. If `ReleaseInventory` is
processed twice (e.g., due to a retry), the second invocation should be
harmless. This is critical for reliability in asynchronous systems.
`Inventory.release()` returns the quantity in `reserved_quantities` for the
order and adds the order to `released_order_ids`. A second release finds the
order there and changes nothing. A release that arrives before its reservation
returns nothing, and the reservation that follows is skipped.

The full source below also has the command handlers that carry out each
command: reserving and releasing stock, creating the shipment, and completing
or cancelling the order.

## Testing the Process Manager

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch20.py:tests"
```

Process managers are best tested through integration tests that verify
the full event chain. In sync processing mode
(`domain.config["event_processing"] = "sync"`), events are processed
immediately. Saving the confirmed order runs the whole chain, and the test
then checks the final state of the order and the stock.

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

??? example "ch20.py, 352 lines"

    ```python
    --8<-- "guides/getting-started/tutorial/ch20.py:full"
    ```

## Next

[Chapter 21: Advanced Query Patterns →](21-query-patterns.md)
