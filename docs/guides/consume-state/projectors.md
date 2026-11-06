# Projectors

<span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Projectors are specialized event handlers responsible for maintaining
[projections](./projections.md) by listening to domain events and updating
projection data accordingly. They apply your domain events to your read models,
so each projection reflects the latest changes in your domain.

## How Projectors Work

When an aggregate raises an event, the following sequence occurs:

```mermaid
sequenceDiagram
  autonumber
  Aggregate->>Event Store: Persist event
  Event Store-->>Engine: New event available
  Engine->>Engine: Match event to subscribed projectors
  Engine->>Projector: Invoke @on handler (within UoW)
  Projector->>Repository: Load/create projection record
  Projector->>Repository: Persist updated projection
  Note over Projector,Repository: UoW commits atomically
```

1. An aggregate raises an event and is persisted. The event is written to the
   event store.
2. The Protean Engine's subscription detects the new event.
3. The engine matches the event to all projectors subscribed to that stream
   category.
4. Each matching `@on` handler is invoked within its own Unit of Work.
5. The handler loads or creates the projection record via
   `current_domain.repository_for()`.
6. Changes to the projection are committed atomically when the UoW completes.

If the handler raises an exception, the UoW rolls back and the event may
be retried depending on the subscription configuration.

## Defining a Projector

Projectors are defined using the `Domain.projector` decorator and must be
associated with a specific projection via `projector_for`:

??? example "The elements this example uses"

    ```python
    --8<-- "guides/consume-state/002.py:elements"
    ```

```python hl_lines="1-2"
--8<-- "guides/consume-state/002.py:inventory_projector"
```

You must also specify which events to listen to, with either `aggregates` or
`stream_categories`. `aggregates` takes a list of aggregate classes and Protean
derives the [stream
categories](../../concepts/async-processing/stream-categories.md)
automatically, while `stream_categories` takes a list of stream category names
for more fine-grained control. When both are specified, `stream_categories`
takes precedence.

!!! note "Required: `projector_for`"
    Every projector must specify `projector_for`, the projection class it
    maintains. Omitting it raises `IncorrectUsageError`.

## Event Handling with `@on`

Projectors use the `@on` decorator (an alias for `@handle`) to specify which
events they respond to:

```python hl_lines="5 21"
--8<-- "guides/consume-state/002.py:inventory_projector"
```

A single projector can handle multiple events. Multiple projectors can also
handle the same event:

??? example "The elements this example uses"

    ```python
    --8<-- "guides/consume-state/projectors/001.py:elements"
    ```

```python
--8<-- "guides/consume-state/projectors/001.py:projectors"
```

## Cross-Aggregate Projections

Projectors can listen to events from multiple aggregates to create
comprehensive views:

??? example "The elements this example uses"

    ```python
    --8<-- "guides/consume-state/projectors/002.py:elements"
    ```

```python
--8<-- "guides/consume-state/projectors/002.py:cross_aggregate"
```

For more granular control, use
[stream categories](../../concepts/async-processing/stream-categories.md)
instead of aggregates. A stream category is qualified with the domain name
(`<domain>::<aggregate>`), so read it from the registered aggregate's
`meta_.stream_category` or write it in full. A bare `"order"` never matches:

```python
--8<-- "guides/consume-state/projectors/002.py:stream_categories"
```

## Idempotency

Projectors should be idempotent to handle duplicate events gracefully:

??? example "The elements this example uses"

    ```python
    --8<-- "guides/consume-state/projectors/003.py:elements"
    ```

```python
--8<-- "guides/consume-state/projectors/003.py:projector"
```

### At-least-once delivery

Event delivery to projectors is at-least-once. The outbox republishes a message
after a publish-then-crash, and a broker can redeliver a message whose
read-model write committed before the message was acknowledged. The same event
therefore reaches a projector more than once, carrying the same
`_metadata.headers.id` each time. An accumulating projector (`total_reviews +=
1`) will double-count unless you make it idempotent.

The safest design is an idempotent upsert, as above: recompute or set the value
rather than increment it, so re-applying the same event is harmless.

### Opting into built-in deduplication

When a projector genuinely cannot be expressed as an upsert, opt into
framework-managed deduplication with `idempotent=True`:

??? example "The elements this example uses"

    ```python
    --8<-- "guides/consume-state/projectors/004.py:elements"
    ```

```python
--8<-- "guides/consume-state/projectors/004.py:projector"
```

Each handler method records a `(message_id, handler)` marker in the same
transaction as its read-model write, so a redelivered event is skipped. This is
atomic (exactly-once) only for a projection backed by a transactional provider.
With that provider, the marker and the read model share one transaction. For a
cache-backed projection the option has no effect and you must write an
idempotent upsert instead. The marker table is created only for domains that
use the option; run `protean db setup` to create it. The decision record on
consume-side idempotency for projectors
([ADR-0017](../../adr/0017-consume-side-idempotency-for-projectors.md))
explains the design and its boundaries.

Keep three boundaries in mind:

- **Use a relational projection in production**: The exactly-once and
  concurrency guarantees rely on a transactional provider that materializes the
  marker's unique index. The in-memory provider enforces neither, so there the
  option only skips ordinary sequential redeliveries.
- **Adding the option to an existing deployment needs a schema change**: The
  marker table appears only once a projector sets `idempotent=True`. Run
  `protean db setup` (or your migration tool) before deploying, or the first
  delivery fails querying a missing table.
- **Markers accumulate**: One row is written per `(message_id, handler)`. Prune
  markers older than your redelivery/recovery window by running `protean
  idempotency cleanup` periodically (from cron). The retention window and batch
  size come from `[consume_idempotency.cleanup]` (default 7 days / 5000 rows).
  Renaming a projector method changes its `handler` identity, orphaning its old
  markers, which the same cleanup eventually removes.

## Transient-failure retries

When a handler method fails with a transient exception, a projector can retry
it *in place*. The retry runs before the message is ever re-delivered or routed
to the DLQ. Set `retries` (and optionally `backoff` / `retry_exceptions`) on
the projector, exactly as on [event
handlers](event-handlers.md#transient-failure-retries):

??? example "The elements this example uses"

    ```python
    --8<-- "guides/consume-state/projectors/005.py:elements"
    ```

```python
--8<-- "guides/consume-state/projectors/005.py:projector"
```

Each attempt runs in a fresh Unit of Work. The failed attempt's Unit of Work
rolls back any partial read-model write before the next attempt begins. This
retry is the natural fix for a concurrency race in which a level-triggered
event is delivered twice and both runs take the create path for the same
read-model key. The losing run hits a primary-key conflict (a
`TransactionError`, which the version/OCC retry does *not* cover). Adding
`TransactionError` to `retry_exceptions` lets the losing run retry instead of
aborting the command under `event_processing=sync`.

The retry re-runs the *same* handler, and the runs converge automatically only
if the handler re-checks existence each time. Write the handler as an
idempotent upsert (get-or-create, as under [Idempotency](#idempotency) above)
instead of an unconditional `repo.add(...)`. On the retry the winning run's
record is now visible, so the handler takes the update path and commits
cleanly.

The behaviour is identical to event and command handlers: it is opt-in and
disabled unless `retries` is set or `server.transient_retry` is enabled. See
[`server.transient_retry`](../../reference/configuration/index.md) for
domain-wide defaults.

## Event Ordering

Be aware that events may not always arrive in the expected order. Design
projectors to handle out-of-order events:

??? example "The elements this example uses"

    ```python
    --8<-- "guides/consume-state/projectors/006.py:elements"
    ```

```python
--8<-- "guides/consume-state/projectors/006.py:projector"
```

When two events about the same entity must never be applied at the same time,
set `sequential_by` to a field carried by every handled event. For example, set
`sequential_by="product_id"`. Events in the same stream category with the same
field value are then processed one at a time and in publish order. This
ordering needs a broker that supports partitioning and a stream subscription.
Events from different categories are not ordered against each other. A
projector over two aggregates can therefore still apply a `Customer` event and
an `Order` event for the same customer at the same time. See [Sequential
processing](../../reference/server/sequential-by.md).

## Error Handling

A projector should catch the errors it expects, such as `ObjectNotFoundError`,
and log and re-raise any other error:

??? example "The elements this example uses"

    ```python
    --8<-- "guides/consume-state/projectors/007.py:elements"
    ```

```python
--8<-- "guides/consume-state/projectors/007.py:projector"
```

## Handling Deletions

When an event means a projection record should be removed, call `delete()` on a
repository query filtered to that record. `delete()` returns the number of
records it removed:

??? example "The elements this example uses"

    ```python
    --8<-- "guides/consume-state/projectors/008.py:elements"
    ```

```python
--8<-- "guides/consume-state/projectors/008.py:projector"
```

`delete()` removes only the records the query returns. A query returns at most
the projection's `limit` (100 by default). When a filter can match more records
than that, call `.limit(None)` before `delete()`.

## Complete Example

In the example below, two projectors maintain two read models from a single
aggregate:

```python hl_lines="65-75 77-85 88-117 120-147"
--8<-- "guides/consume-state/002.py:full"
```

This example demonstrates:

- **Two projections serve two uses**: `ProductInventory` for detailed inventory
  tracking and `ProductCatalog` for simplified browsing
- **Multiple Projectors**: Each projection has its own dedicated projector
- **Two projectors react to the same events**: Both projectors respond to the
  same events but update different projections
- **Projections update in real time**: Projections are automatically updated
  when domain events occur

## Testing Projectors

### Unit Testing

Test individual projector methods by creating events and calling the methods
directly:

```python
--8<-- "guides/consume-state/projectors/009.py:unit"
```

### Integration Testing

Test the complete flow by raising events from aggregates:

```python
--8<-- "guides/consume-state/projectors/009.py:integration"
```

---

!!! seealso "See also"
    **Concept overviews:**

    - [Projections](../../concepts/building-blocks/projections.md): Read-optimized views in CQRS.
    - [Projectors](../../concepts/building-blocks/projectors.md): Specialized handlers that maintain projections.

    **Patterns:**

    - [Design Events for Consumers](../../patterns/design-events-for-consumers.md): Structuring events so projectors can build reliable read models.
    - [Idempotent Event Handlers](../../patterns/idempotent-event-handlers.md): Ensuring projectors handle replayed events correctly.
