# Chapter 7: Projections and Projectors

In this chapter we will create a `BookCatalog` projection — a
read-optimized view that stays in sync with our Book aggregate through
events.

!!! note "CQRS Concept"
    Projections are a **CQRS-specific** pattern — they separate your read
    model from your write model. In the pure DDD approach, you query
    aggregates directly through repositories. Projections become valuable
    when your read and write needs diverge.

## Why Projections?

Our aggregates enforce business rules, but for listing books in a catalog
we want flat, fast data — no nested value objects, no business logic.
Projections give us that.

## Defining a Projection

A projection is a flat data structure optimized for queries:

```python
--8<-- "guides/getting-started/tutorial/ch07.py:projection"
```

Notice that the projection has only simple fields — `String`, `Float`,
`Identifier`. No associations, no value objects. The `identifier=True`
on `book_id` marks it as the primary key.

## Building a Projector

A **projector** listens to events and maintains the projection:

```python
--8<-- "guides/getting-started/tutorial/ch07.py:projector"
```

The projector is registered with `projector_for=BookCatalog` (the
projection it maintains) and `aggregates=[Book]` (the aggregates whose
events it listens to). The `@on()` decorator specifies which event
triggers each method.

When a `BookAdded` event fires, `on_book_added` creates a catalog entry.
When `BookPriceUpdated` fires, `on_price_updated` updates the existing
entry.

## Querying the Projection

Projections are queried the same way as aggregates — through a
repository:

```python
--8<-- "guides/getting-started/tutorial/ch07.py:usage"
```

Run it:

```shell
$ python bookshelf.py
=== Adding Books ===

=== Book Catalog (Projection) ===
Total entries: 3
  The Great Gatsby by F. Scott Fitzgerald — $12.99
  Brave New World by Aldous Huxley — $14.99
  1984 by George Orwell — $11.99

=== Updating Price ===
Updated: The Great Gatsby — $15.99

All checks passed!
```

Notice that we never updated the projection directly — the projector
reacted to events and kept it in sync automatically. The catalog always
reflects the latest state of the Book aggregate.

## What We Built

- A **`BookCatalog` projection** — flat, query-optimized data.
- A **`BookCatalogProjector`** — listens to Book events and maintains
  the projection.
- Automatic sync: adding or updating a book immediately updates the
  catalog.

In the next chapter, we will switch from in-memory storage to a real
PostgreSQL database.

## Full Source

```python
--8<-- "guides/getting-started/tutorial/ch07.py:full"
```

## Next

[Chapter 8: Connecting a Real Database →](08-persistence.md)
