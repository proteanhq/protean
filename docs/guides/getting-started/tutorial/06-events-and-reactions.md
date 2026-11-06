# Chapter 6: Raise events and react to them

You define domain events, raise them from aggregates, and build event handlers.
The event handlers create Inventory records automatically whenever a book is
added to the catalog. Every operation runs through the command pipeline
introduced in Chapter 5.

!!! note "Events in DDD and CQRS"
    Domain events and event handlers are a core DDD concept. You use them in
    **both** the DDD and CQRS approaches. The difference is in how events get
    triggered: in CQRS, commands flow through handlers that invoke aggregate
    methods; in pure DDD, Application Services do the same job directly.

## Defining Events

When a book is added to the catalog, we want to record that fact as a **domain
event**. Events describe something that already happened. Name them in past
tense:

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch06.py:book_event"
```

## Raising Events from Aggregates

Events are raised inside aggregate methods using `self.raise_()`:

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch06.py:book_aggregate"
```

When `add_to_catalog()` is called, the `BookAdded` event is collected on the
aggregate. Protean dispatches the event when the aggregate is persisted.
Protean dispatches in this order, so a transaction failure never loses an
event.

Let's also raise events from the Order aggregate:

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch06.py:order_aggregate"
```

And define the Order events:

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch06.py:order_events"
```

## The Inventory Aggregate

Before we build the event handler, we need an aggregate for it to create. Let's
create an `Inventory` aggregate:

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch06.py:inventory"
```

## Reacting with Event Handlers

An **event handler** listens for specific events and performs side effects.
Let's create one that stocks inventory for each book added to the catalog:

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch06.py:book_event_handler"
```

Notice that the handler is registered with `part_of=Book`. It listens to events
from the Book aggregate. When a `BookAdded` event is raised, the
`on_book_added` method runs automatically and creates an inventory record.

We can also handle Order events to send notifications:

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch06.py:order_event_handler"
```

A single event handler class can handle multiple event types.

## Define commands for the full flow

Just like Chapter 5, we define commands and handlers for every state
change. Here are the commands for placing, confirming, and shipping
orders:

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch06.py:commands"
```

And the command handlers that orchestrate the flow:

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch06.py:command_handlers"
```

The `BookCommandHandler` calls `book.add_to_catalog()` which raises the
`BookAdded` event. The `OrderCommandHandler` loads the order from the
repository, calls the domain method, and persists the result. Protean
dispatches the events automatically when the repository saves the aggregate.

## Run the flow end to end

In the complete flow, adding a book triggers inventory creation. Order
lifecycle events trigger notifications. You call `domain.process()` for every
operation:

```python
# fragment
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

Notice that we never called the event handlers ourselves. They ran
automatically when events were raised and the aggregate was persisted. The Book
aggregate knows nothing about Inventory; the event handler provides the
decoupling. As in Chapter 5, every operation runs as an explicit command.

## What We Built

- **`BookAdded`**, **`OrderConfirmed`**, **`OrderShipped`** events, immutable facts recorded when state
  changes.
- **`self.raise_()`**: Raises events from aggregate methods.
- **`BookEventHandler`**: Reacts to `BookAdded` by creating inventory.
- **`OrderEventHandler`**: Reacts to order lifecycle events.
- **`PlaceOrder`**, **`ConfirmOrder`**, **`ShipOrder`** commands. You call
  `domain.process()` for every operation.
- A fully decoupled flow: when you add a book, the event handler stocks
  inventory automatically.

The next chapter builds a read-optimized projection for browsing the book
catalog. The read side of CQRS.

## See the full source

??? example "ch06.py, 301 lines"

    ```python
    --8<-- "guides/getting-started/tutorial/ch06.py:full"
    ```

## Next

[Chapter 7: Projections and Projectors →](07-projections.md)
