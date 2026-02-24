# Chapter 10: Entities Inside Aggregates

Business accounts can have multiple authorized signatories — people who
are allowed to operate the account. Each signatory has a name, role, and
email. In this chapter we will add an **entity** inside the Account
aggregate and learn how event-sourced aggregates handle child entities
through events.

## Defining the Entity

An entity is an object with identity that lives inside an aggregate:

```python
--8<-- "guides/getting-started/es-tutorial/ch10.py:entity"
```

The entity is declared with `part_of=Account` — it cannot exist
independently. It is always accessed and persisted through its parent
aggregate.

## Events for Entity Operations

Adding and removing signatories are state changes, so they flow through
events:

```python
--8<-- "guides/getting-started/es-tutorial/ch10.py:signatory_events"
```

## Connecting Entities to the Aggregate

The `Account` aggregate uses `HasMany` to declare a collection of
signatories, and `@apply` handlers manage the entity lifecycle:

```python
signatories = HasMany(AuthorizedSignatory)

def add_signatory(self, name: str, role: str, email: str) -> None:
    self.raise_(SignatoryAdded(
        account_id=str(self.id),
        name=name,
        role=role,
        email=email,
    ))

@apply
def on_signatory_added(self, event: SignatoryAdded):
    self.add_signatories(
        AuthorizedSignatory(name=event.name, role=event.role, email=event.email)
    )
```

Key points:

- **`self.add_signatories()`** is a dynamic method injected by
  `HasMany`. It adds a child entity to the collection.
- During **event replay** (`from_events()`), the same `@apply` handler
  runs, rebuilding the entity collection from events.
- Entity identity within the aggregate is managed automatically.

## The Rule

In event-sourced aggregates, **all state changes flow through events**
— including entity creation and removal. You never modify the
`signatories` collection directly. You raise an event, and the `@apply`
handler does the mutation.

This ensures that replaying events produces the exact same entity
collection every time.

## What We Built

- An **AuthorizedSignatory** entity inside the Account aggregate.
- **`HasMany`** to declare entity collections.
- Events for entity lifecycle (**SignatoryAdded**, **SignatoryRemoved**).
- `@apply` handlers that use **`self.add_signatories()`** and
  **`self.remove_signatories()`**.
- The principle that entity changes flow through events, just like
  all other state.

Part II is complete. We have a growing platform with projections, event
handlers, async processing, cross-aggregate coordination, and child
entities. In Part III, we will face real-world challenges: changing
requirements, performance problems, regulatory inquiries, and external
integrations.

## Full Source

```python
--8<-- "guides/getting-started/es-tutorial/ch10.py:full"
```

## Next

[Chapter 11: When Requirements Change — Event Upcasting →](11-event-upcasting.md)
