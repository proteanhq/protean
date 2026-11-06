# Chapter 13: Checking Before You Ship with Domain Services

A customer just complained: they ordered five copies of a book, the order was
confirmed, but only three were in stock. The current system confirms orders
blindly. It never checks inventory. We need business logic that spans two
aggregates (Order and Inventory). That logic does not belong in either
aggregate. It belongs in a **domain service**.

## What Is a Domain Service?

A domain service is a stateless object that encapsulates business logic
spanning two or more aggregates. Unlike aggregates, domain services:

- Have no identity and no lifecycle.
- Are invoked from command handlers or application services.
- Can run pre-invariants and post-invariants for validation.
- Are always associated with the aggregates they coordinate.

### When to Use a Domain Service (vs. an Event Handler)

You might wonder: couldn't we use an event handler to check
inventory when an order is confirmed? The key difference is
**transactional consistency**:

| Approach | Guarantees |
|----------|-----------|
| **Domain service** | Synchronous. Inventory is checked *before* the order is confirmed. If the stock it reads is insufficient, the command fails and the order stays `PENDING`. |
| **Event handler** | Eventually consistent; the order is confirmed first, then the handler runs. If stock is insufficient, you need compensating actions. |

When the business rule says "this must not happen", like confirming an order
without sufficient stock, use a domain service. When the reaction can happen
after the fact, use event handlers.

This chapter uses both. The domain service checks stock and confirms the order.
Reserving the stock changes a second aggregate, Inventory, so it happens in its
own transaction, through an event and a command.

## The Fulfillment Service

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch13.py:service"
```

The service has four parts:

1. **`part_of=[Order, Inventory]`**: The service is associated with both
   aggregates. Protean requires domain services to declare which aggregates
   they coordinate.

2. **`__init__`**: The constructor receives the aggregates and calls
   `super().__init__()` with all of them, which keeps them on the service.
   Protean wires the invariants when it registers the class. The invariants run
   even if a service leaves this call out.

3. **`@invariant.pre`**: The `all_items_in_stock` invariant runs
   *before* `confirm_order()` executes. If any item is out of stock, a
   `ValidationError` is raised and the order is never confirmed. The check adds
   up the order's lines for each title, so two lines for the same book are
   checked against the stock together. Pre-invariants are the domain service's
   main value. Pre-invariants check a cross-aggregate rule before anything
   changes.

4. **`confirm_order()`**: The domain method that performs the mutation. It
   confirms the order. `Order.confirm()` raises `OrderConfirmed` with the
   customer's name and the quantity ordered for each title. The service does
   not touch Inventory.

## Updating the Command Handler

The `ConfirmOrder` handler now loads inventory records and delegates to
the domain service:

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch13.py:handler"
```

The handler's job is orchestration, not business logic:

1. Load the order from the repository. If the order is already confirmed, stop,
   so that a repeated `ConfirmOrder` changes nothing.
2. Load the relevant inventory records.
3. Pass everything to the domain service.
4. Persist the order. Only the order.

If the inventory check fails, the `ValidationError` propagates to the API
layer. The exception handlers we registered in Chapter 10 then return a `400
Bad Request` automatically. Nothing was saved, so the order stays `PENDING`.

A handler changes one aggregate per transaction. The handler loads the
inventory records so the service can check them. It does not save them.

The handlers find a book's stock by its title, so the tutorial assumes each
title has one inventory record. If two inventory records share a title, the
stock reservation in the next section fails with `TooManyObjectsError`. By then
the order is already saved.

## Reserving the Stock

`OrderConfirmed` lists each title once, with its total quantity. An event
handler in Order's cluster reacts to it and sends one `ReserveInventory`
command per title. Inventory's command handler does the reservation:

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch13.py:reservation"
```

The event handler is part of Order's cluster because Order owns
`OrderConfirmed`. It does not change Inventory itself. The event handler sends
the change to Inventory as a command. `reserve_inventory` belongs in the
`OrderEventHandler` from Chapter 6, next to its `on_order_confirmed`
notification. Add the method to that class; do not define a second
`OrderEventHandler`. One handler can have several methods for the same event,
and each one runs.

Events can be delivered more than once, so the command handler checks
`reserved_order_ids` first and skips an order it has already reserved for.
Without that check, a redelivered `OrderConfirmed` would reserve the stock
twice. The check works because an order reserves each book once: two lines for
the same book arrive as one command with the summed quantity. The list grows by
one id for every order that reserves the book. The repository loads the list
every time it loads the inventory record.

The service checks the stock and Inventory's command handler reserves it, in
two separate transactions. The service checks the stock it read. The
reservation runs later, in its own transaction, and can still fail: another
order can take the last copies in between. `Inventory.reserve()` checks the
stock again and raises `ValidationError`, so the stock never goes below zero.
The order, though, is already saved as `CONFIRMED`, and no stock is reserved
for it. With the `"sync"` settings below, `domain.process(ConfirmOrder(...))`
then raises `TransactionError`. With asynchronous processing, the reservation
fails in the server instead.

A real store has to recover from that failure. A common way is a compensating
step. Inventory's command handler catches the error and raises an event such as
`ReservationFailed`. An event handler reacts to `ReservationFailed` by
cancelling the order. In Chapter 20, you build this kind of compensation with a
process manager for a failed shipment. Chapter 20 does not build compensation
for a failed reservation. You can read there how to add it.

This chapter's domain sets `command_processing` and `event_processing` to
`"sync"`, so the whole chain runs before `domain.process()` returns. With
asynchronous processing, the reservation runs shortly after, in the server.

## Testing the Domain Service

Test both the happy path and the out-of-stock scenario:

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch13.py:tests"
```

Notice that we test the domain service directly, with no command processing and
no repositories. The tests open a domain context because `Order.confirm()`
raises an event. The service takes aggregates as input and changes them in
memory, so it is easy to unit test. The happy-path test also checks that the
service does not change the inventory. The stock is still 10 after the order is
confirmed.

## What We Built

- An **`OrderFulfillmentService`** domain service that validates
  inventory across aggregates before confirming an order.
- A **`@invariant.pre`** that enforces "all items must be in stock"
  as a cross-aggregate business rule.
- An updated **`ConfirmOrder`** handler that delegates to the service and
  persists only the order.
- An **`OrderConfirmed`** event, an event handler method that turns it into
  one `ReserveInventory` command per title, and an Inventory command handler
  that reserves the stock once per order.
- Tests verifying both success and failure paths.

In the next chapter, we will integrate with an external book supplier
using a subscriber.

## Full Source

??? example "ch13.py, 253 lines"

    ```python
    --8<-- "guides/getting-started/tutorial/ch13.py:full"
    ```

## Next

[Chapter 14: Connecting to the Outside World with Subscribers →](14-subscribers.md)
