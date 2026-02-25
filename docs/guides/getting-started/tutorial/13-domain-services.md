# Chapter 13: Check Before You Ship — Domain Services

A customer just complained: they ordered five copies of a book, the
order was confirmed, but only three were in stock. The current system
confirms orders blindly — it never checks inventory. We need business
logic that spans two aggregates (Order and Inventory), and that logic
does not belong in either aggregate. It belongs in a **domain service**.

## What Is a Domain Service?

A domain service is a stateless object that encapsulates business logic
spanning two or more aggregates. Unlike aggregates, domain services:

- Have no identity and no lifecycle.
- Are invoked from command handlers or application services.
- Can run pre-invariants and post-invariants for validation.
- Are always associated with the aggregates they coordinate.

### When to Use a Domain Service (vs. an Event Handler)

You might wonder: couldn't we just use an event handler to check
inventory when an order is confirmed? The key difference is
**transactional consistency**:

| Approach | Guarantees |
|----------|-----------|
| **Domain service** | Synchronous, single transaction — inventory is checked *before* the order is confirmed. If stock is insufficient, the entire operation rolls back. |
| **Event handler** | Eventually consistent — the order is confirmed first, then the handler runs. If stock is insufficient, you need compensating actions. |

Use a domain service when the business rule says "this must not happen" —
like confirming an order without sufficient stock. Use event handlers when
the reaction can happen after the fact.

## The Fulfillment Service

```python
--8<-- "guides/getting-started/tutorial/ch13.py:service"
```

Let's break down how this works:

1. **`part_of=[Order, Inventory]`** — The service is associated with both
   aggregates. Protean requires domain services to declare which aggregates
   they coordinate.

2. **`__init__`** — The constructor receives the aggregates and calls
   `super().__init__()` with all of them. This is required for Protean to
   track the aggregates and run invariants.

3. **`@invariant.pre`** — The `all_items_in_stock` invariant runs
   *before* `confirm_order()` executes. If any item is out of stock, a
   `ValidationError` is raised and the order is never confirmed. Pre-invariants
   are the domain service's main value — they enforce cross-aggregate
   business rules atomically.

4. **`confirm_order()`** — The domain method that performs the actual
   mutation: reserving inventory for each item and confirming the order.

## Updating the Command Handler

The `ConfirmOrder` handler now loads inventory records and delegates to
the domain service:

```python
--8<-- "guides/getting-started/tutorial/ch13.py:handler"
```

The handler's job is orchestration, not business logic:

1. Load the order from the repository.
2. Load the relevant inventory records.
3. Pass everything to the domain service.
4. Persist the mutated aggregates.

If the inventory check fails, the `ValidationError` propagates to the
API layer and returns a `400 Bad Request` automatically (thanks to the
exception handlers we registered in Chapter 10).

## Testing the Domain Service

Test both the happy path and the out-of-stock scenario:

```python
--8<-- "guides/getting-started/tutorial/ch13.py:tests"
```

Notice that we test the domain service directly — no need for a full
domain context or command processing. The service is a plain Python
object that takes aggregates as input. This makes domain services easy
to unit test.

## What We Built

- An **`OrderFulfillmentService`** domain service that validates
  inventory across aggregates before confirming an order.
- A **`@invariant.pre`** that enforces "all items must be in stock"
  as a cross-aggregate business rule.
- An updated **`ConfirmOrder`** handler that delegates to the service.
- Tests verifying both success and failure paths.

In the next chapter, we will integrate with an external book supplier
using a subscriber.

## Full Source

```python
--8<-- "guides/getting-started/tutorial/ch13.py:full"
```

## Next

[Chapter 14: Connecting to the Outside World →](14-subscribers.md)
