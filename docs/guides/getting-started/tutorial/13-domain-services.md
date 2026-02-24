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

## The Fulfillment Service

```python
--8<-- "guides/getting-started/tutorial/ch13.py:service"
```

The `OrderFulfillmentService` takes an Order and matching Inventory
records, checks that every item is in stock, and either confirms the
order (reducing inventory) or raises a `ValidationError`.

## Updating the Command Handler

The `ConfirmOrder` handler now loads inventory records and delegates to
the domain service:

```python
--8<-- "guides/getting-started/tutorial/ch13.py:handler"
```

If the inventory check fails, the `ValidationError` propagates to the
API layer and returns a `400 Bad Request` automatically (thanks to the
exception handlers we registered in Chapter 10).

## Testing the Domain Service

Test both the happy path and the out-of-stock scenario:

```python
--8<-- "guides/getting-started/tutorial/ch13.py:tests"
```

## What We Built

- An **`OrderFulfillmentService`** domain service that validates
  inventory across aggregates before confirming an order.
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
