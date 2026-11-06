# Chapter 10: Add entities inside an aggregate

Business accounts can have multiple authorized signatories. People who are
allowed to operate the account. Each signatory has a name, role, and email. You
now add an **entity** inside the Account aggregate. An event-sourced aggregate
adds and removes child entities only through events.

## Defining the Entity

An entity is an object with identity that is part of an aggregate:

```python
# fragment
--8<-- "guides/getting-started/es-tutorial/ch10.py:entity"
```

The entity is declared with `part_of=Account`. It cannot exist independently.
It is always accessed and persisted through its parent aggregate.

## Define events for entity changes

The account's state changes when it adds or removes a signatory. So the
aggregate raises an event for each change:

```python
# fragment
--8<-- "guides/getting-started/es-tutorial/ch10.py:signatory_events"
```

## Connecting Entities to the Aggregate

The `Account` aggregate uses `HasMany` to declare a collection of signatories.
Its `@apply` handlers add entities to that collection and remove them:

```python
# fragment
--8<-- "guides/getting-started/es-tutorial/ch10.py:signatories_field"
--8<-- "guides/getting-started/es-tutorial/ch10.py:add_signatory"
--8<-- "guides/getting-started/es-tutorial/ch10.py:on_signatory_added"
```

Key points:

- **`self.add_signatories()`** is a dynamic method injected by
  `HasMany`. It adds a child entity to the collection.
- During **event replay** (`from_events()`), the same `@apply` handler
  runs, rebuilding the entity collection from events.
- Protean generates each entity's identity within the aggregate automatically.

## Change entities only through events

In event-sourced aggregates, **every state change is recorded as an event**,
including entity creation and removal. You never modify the `signatories`
collection directly. You raise an event, and the `@apply` handler does the
mutation.

When you replay the events, the `@apply` handlers rebuild the exact same entity
collection every time.

## What We Built

- An **AuthorizedSignatory** entity inside the Account aggregate.
- **`HasMany`** to declare entity collections.
- Events for entity lifecycle (**SignatoryAdded**, **SignatoryRemoved**).
- `@apply` handlers that use **`self.add_signatories()`** and
  **`self.remove_signatories()`**.
- The principle that entity changes flow through events, just like
  all other state.

That completes Part II. We have a growing platform with projections, event
handlers, async processing, cross-aggregate coordination, and child
entities. In Part III, we will face real-world challenges: changing
requirements, performance problems, regulatory inquiries, and external
integrations.

## Read the full source

??? example "ch10.py, 332 lines"

    ```python
    --8<-- "guides/getting-started/es-tutorial/ch10.py:full"
    ```

## Continue to the next chapter

[Chapter 11: Upcasting Events When Requirements Change →](11-event-upcasting.md)
