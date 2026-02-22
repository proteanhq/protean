# Chapter 6: Events and Reactions

In this chapter we will define domain events, raise them from aggregates,
and build event handlers that react automatically — creating Inventory
records whenever a book is added to the catalog.

## Defining Events

When a book is added to the catalog, we want to record that fact as a
**domain event**. Events are named in past tense — they describe
something that already happened:

```python
{! docs_src/guides/getting-started/tutorial/ch06.py [ln:51-59] !}
```

## Raising Events from Aggregates

Events are raised inside aggregate methods using `self.raise_()`:

```python
{! docs_src/guides/getting-started/tutorial/ch06.py [ln:28-48] !}
```

When `add_to_catalog()` is called, the `BookAdded` event is collected on
the aggregate. It will be dispatched when the aggregate is persisted —
this ensures events are never lost due to transaction failures.

Let's also raise events from the Order aggregate:

```python
{! docs_src/guides/getting-started/tutorial/ch06.py [ln:69-89] !}
```

And define the Order events:

```python
{! docs_src/guides/getting-started/tutorial/ch06.py [ln:97-108] !}
```

## The Inventory Aggregate

Before we build the event handler, we need something for it to manage.
Let's create an `Inventory` aggregate:

```python
{! docs_src/guides/getting-started/tutorial/ch06.py [ln:112-121] !}
```

## Reacting with Event Handlers

An **event handler** listens for specific events and performs side
effects. Let's create one that stocks inventory when a book is added:

```python
{! docs_src/guides/getting-started/tutorial/ch06.py [ln:125-139] !}
```

Notice that the handler is registered with `part_of=Book` — it listens
to events from the Book aggregate. When a `BookAdded` event is raised,
the `on_book_added` method runs automatically and creates an inventory
record.

We can also handle Order events to send notifications:

```python
{! docs_src/guides/getting-started/tutorial/ch06.py [ln:143-157] !}
```

A single event handler class can handle multiple event types.

## End-to-End Flow

Let's see the complete flow — adding a book triggers inventory creation,
and order lifecycle events trigger notifications:

```python
{! docs_src/guides/getting-started/tutorial/ch06.py [ln:180-] !}
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
provides the decoupling.

## What We Built

- **`BookAdded`**, **`OrderConfirmed`**, **`OrderShipped`** events —
  immutable facts recorded when state changes.
- **`self.raise_()`** — raises events from aggregate methods.
- **`BookEventHandler`** — reacts to `BookAdded` by creating inventory.
- **`OrderEventHandler`** — reacts to order lifecycle events.
- A fully decoupled flow where adding a book automatically stocks
  inventory.

In the next chapter, we will build a read-optimized projection for
browsing the book catalog.

## Full Source

```python
{! docs_src/guides/getting-started/tutorial/ch06.py !}
```

## Next

[Chapter 7: Projections →](07-projections.md)
