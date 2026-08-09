# Chapter 15: Fact Events and the Reporting Pipeline

The marketing team wants a reporting dashboard showing current book
information. They don't want to process individual `BookAdded` and
`BookPriceUpdated` events. They want a single event per change containing the
complete, current book state.

## Delta Events vs. Fact Events

So far, our events have been **delta events**. They describe *what changed*:

| Event | Content |
|-------|---------|
| `BookAdded` | `book_id`, `title`, `author`, `price` |
| `BookPriceUpdated` | `book_id`, `new_price` |

A consumer processing `BookPriceUpdated` only knows the new price, not the
title, author, or any other field. To build a complete picture, it must process
every event from the beginning.

**Fact events** solve this. A fact event contains the *complete current
state* of the aggregate after each change:

| Event | Content |
|-------|---------|
| `BookFactEvent` | `id`, `title`, `author`, `isbn`, `price`, `description` |

Every time a Book is persisted, Protean automatically generates a fact
event with the full state.

## Enabling Fact Events

Add `fact_events=True` to the Book aggregate:

```python
--8<-- "guides/getting-started/tutorial/ch15.py:aggregate"
```

That's it. Protean now generates a `BookFactEvent` automatically
whenever a Book is persisted.

## Building a Report Projection

The marketing dashboard needs a `BookReport` projection populated from
fact events:

```python
--8<-- "guides/getting-started/tutorial/ch15.py:projection"
```

## Consuming Fact Events

Fact events flow through a separate stream, `<domain>::book-fact` instead of `<domain>::book`. An event
handler subscribed to the aggregate will receive both delta and fact events.
When running the async server (`protean server`), the handler is invoked automatically:

```python
--8<-- "guides/getting-started/tutorial/ch15.py:handler"
```

The handler receives the complete state and can overwrite the projection, no
need to track deltas.

## Verifying

```python
--8<-- "guides/getting-started/tutorial/ch15.py:usage"
```

Every time a book is added or updated, a fact event with the complete current
state is written to the event store. The marketing team never needs to
understand the internal event schema. They just consume fact events.

## What We Built

- **Fact events** with `fact_events=True` on the Book aggregate.
- A **`BookReport`** projection for the marketing dashboard.
- A **`BookReportHandler`** consuming fact events from the event store.
- Understanding of delta vs. fact events and when to use each.

That completes Part III. The bookstore now runs asynchronously, validates
inventory before shipping, integrates with external suppliers, and
feeds a marketing dashboard. In the next chapter, we will enter
production operations, starting with message tracing.

## Full Source

```python
--8<-- "guides/getting-started/tutorial/ch15.py:full"
```

## Next

[Chapter 16: Following the Trail with Message Tracing →](16-message-tracing.md)
