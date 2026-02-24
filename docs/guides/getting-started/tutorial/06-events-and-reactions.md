# Chapter 6: Events and Reactions

In this chapter we will define domain events, raise them from aggregates,
and build event handlers that react automatically — creating Inventory
records whenever a book is added to the catalog. We will wire everything
through the command pipeline introduced in Chapter 5.

!!! note "Events in DDD and CQRS"
    Domain events and event handlers are used in **both** the DDD and CQRS
    approaches — they're a core DDD concept. The difference is in how
    events get triggered: in CQRS, commands flow through handlers that
    invoke aggregate methods; in pure DDD, Application Services do the
    same job directly.

## Defining Events

When a book is added to the catalog, we want to record that fact as a
**domain event**. Events are named in past tense — they describe
something that already happened:

```python
--8<-- "guides/getting-started/tutorial/ch06.py:book_event"
```

## Raising Events from Aggregates

Events are raised inside aggregate methods using `self.raise_()`:

```python
--8<-- "guides/getting-started/tutorial/ch06.py:book_aggregate"
```

When `add_to_catalog()` is called, the `BookAdded` event is collected on
the aggregate. It will be dispatched when the aggregate is persisted —
this ensures events are never lost due to transaction failures.

Let's also raise events from the Order aggregate:

```python
--8<-- "guides/getting-started/tutorial/ch06.py:order_aggregate"
```

And define the Order events:

```python
--8<-- "guides/getting-started/tutorial/ch06.py:order_events"
```

## The Inventory Aggregate

Before we build the event handler, we need something for it to manage.
Let's create an `Inventory` aggregate:

```python
--8<-- "guides/getting-started/tutorial/ch06.py:inventory"
```

## Reacting with Event Handlers

An **event handler** listens for specific events and performs side
effects. Let's create one that stocks inventory when a book is added:

```python
--8<-- "guides/getting-started/tutorial/ch06.py:book_event_handler"
```

Notice that the handler is registered with `part_of=Book` — it listens
to events from the Book aggregate. When a `BookAdded` event is raised,
the `on_book_added` method runs automatically and creates an inventory
record.

We can also handle Order events to send notifications:

```python
--8<-- "guides/getting-started/tutorial/ch06.py:order_event_handler"
```

A single event handler class can handle multiple event types.

## Commands for the Full Flow

Just like Chapter 5, we define commands and handlers for every state
change. Here are the commands for placing, confirming, and shipping
orders:

```python
--8<-- "guides/getting-started/tutorial/ch06.py:commands"
```

And the command handlers that orchestrate the flow:

```python
--8<-- "guides/getting-started/tutorial/ch06.py:command_handlers"
```

The `BookCommandHandler` calls `book.add_to_catalog()` which raises
the `BookAdded` event. The `OrderCommandHandler` loads the order from
the repository, calls the domain method, and persists the result — the
events are dispatched automatically on save.

## End-to-End Flow

Let's see the complete flow — adding a book triggers inventory creation,
and order lifecycle events trigger notifications. Everything flows
through `domain.process()`:

```python
--8<-- "guides/getting-started/tutorial/ch06.py:usage"
```

Run it:

```shell
$ python bookshelf.py
Adding book to catalog...
  [Inventory] Stocked 10 copies of 'The Great Gatsby'
  Inventory: The Great Gatsby, qty=10

Placing an order...
Confirming order...
  [Notification] Order e5f6g7h8-... confirmed for Alice Johnson
Shipping order...
  [Notification] Order e5f6g7h8-... shipped to Alice Johnson

All checks passed!
```

Notice that we never called the event handlers ourselves — they ran
automatically when events were raised and the aggregate was persisted.
The Book aggregate knows nothing about Inventory; the event handler
provides the decoupling. And every operation flows through explicit
commands, just like Chapter 5.

## What We Built

- **`BookAdded`**, **`OrderConfirmed`**, **`OrderShipped`** events —
  immutable facts recorded when state changes.
- **`self.raise_()`** — raises events from aggregate methods.
- **`BookEventHandler`** — reacts to `BookAdded` by creating inventory.
- **`OrderEventHandler`** — reacts to order lifecycle events.
- **`PlaceOrder`**, **`ConfirmOrder`**, **`ShipOrder`** commands —
  every operation flows through `domain.process()`.
- A fully decoupled flow where adding a book automatically stocks
  inventory.

In the next chapter, we will build a read-optimized projection for
browsing the book catalog — the read side of CQRS.

## Full Source

```python
--8<-- "guides/getting-started/tutorial/ch06.py:full"
```

## Next

[Chapter 7: Projections and Projectors →](07-projections.md)
