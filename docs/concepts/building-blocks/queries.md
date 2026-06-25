# Queries

A query is an immutable, validated **read intent** -- a named request for data on
the read side of CQRS. Where a command expresses intent to *change* state, a query
expresses intent to *read* it.

Queries are the input to query handlers. A query carries the parameters a read
needs (an identifier, a filter, a page number); the handler answers it from a
projection and returns the result. Queries flow through `domain.dispatch(query)`,
mirroring how commands flow through `domain.process(command)`.

## Facts

### Queries target a projection. { data-toc-label="Target a Projection" }

A query is associated with a projection (a read model) via `part_of`, not with an
aggregate. This places it firmly on the read side: queries describe reads against
the denormalized views that projectors maintain.

### Queries are immutable. { data-toc-label="Immutable" }

Once constructed, a query's fields cannot be changed -- assigning to a field raises
`IncorrectUsageError`. To issue a different read, build a new query.

### Queries are validated at construction. { data-toc-label="Validated" }

Field constraints (`required`, `min_value`, `max_value`, `choices`, and so on) are
enforced when the query is created, before it reaches a handler. An invalid query
raises `ValidationError` immediately.

### Queries carry only basic data. { data-toc-label="Basic Fields" }

A query holds simple field types (and value objects) -- the parameters of a read.
It cannot contain associations (`HasOne`, `HasMany`, `Reference`); those belong to
aggregates.

### Queries are named for what they return. { data-toc-label="Naming" }

Commands are imperative (`PlaceOrder`); queries are named for their result
(`GetOrderById`, `SearchOrders`, `ListActiveCustomers`).

### Queries are lightweight. { data-toc-label="Lightweight" }

Unlike commands and events, queries carry no metadata, stream, or event-store
concerns. They are plain read-intent DTOs, dispatched synchronously and answered
immediately.

## Best Practices

### Keep queries to read parameters. { data-toc-label="Read Parameters Only" }

A query is a parameter object, not a place for behavior. It should not reach into
repositories or compute results -- that is the query handler's job.

### Model one query per read shape. { data-toc-label="One per Read" }

Prefer distinct queries (`GetOrderById`, `SearchOrders`) over a single
parameter-heavy query with many optional fields. Named reads are clearer and
validate more precisely.

---

## Next steps

For practical details on defining queries and answering them, see the guide:

- [Query Handlers](../../guides/consume-state/query-handlers.md) -- Defining
  queries, the `@read` decorator, and dispatching with `domain.dispatch()`.

For related concepts:

- [Query Handlers](./query-handlers.md) -- The read-side handlers that answer queries.
- [Projections](./projections.md) -- The read models queries target.
- [Commands](./commands.md) -- The write-side counterpart (intent to change state).
