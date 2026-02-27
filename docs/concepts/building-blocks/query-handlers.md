# Query Handlers

Query handlers are the read-side counterpart of command handlers. They process
queries -- named, validated read intents -- and return results from projections.

Where command handlers mutate state through aggregates, query handlers read
state from projections. This separation is fundamental to CQRS: writes flow
through `domain.process(command)`, reads flow through
`domain.dispatch(query)`.

**Why not query projections directly?** You can -- and for simple lookups,
`domain.view_for(Projection).get(id)` is perfectly fine. But as read
patterns grow in complexity (filtered searches with pagination, access
control checks, response shaping), that logic needs a home. Scattering it
across API controllers mixes infrastructure with domain concerns. Query
handlers give structured reads the same organized treatment that command
handlers give writes: named intents with validated inputs, routed through
the domain to a dedicated handler.

## Facts

### Query handlers are connected to a projection. { data-toc-label="Connected to Projection" }

Query handlers are always associated with a single projection via `part_of`.
This mirrors how command handlers are connected to aggregates, but on the
read side.

### A query handler contains multiple handler methods. { data-toc-label="Handlers" }

Each method in a query handler is decorated with `@read` and handles a
specific query type. A handler can have methods for different queries,
all targeting the same projection.

### Handler methods use `@read`, not `@handle`. { data-toc-label="@read Decorator" }

The `@read` decorator is intentionally distinct from `@handle`. While
`@handle` wraps execution in a UnitOfWork (for write-side consistency),
`@read` executes the method directly with no transaction wrapping.

### Query handlers always return values. { data-toc-label="Return Values" }

Unlike event handlers (which return nothing) and command handlers (which
optionally return values), query handlers **always** return data. The return
value from the handler method passes through `domain.dispatch()` to the
caller.

### No UnitOfWork wrapping. { data-toc-label="No UoW" }

Query handlers do not create transactions. Reads are stateless and should
never cause side effects. The absence of UoW is enforced by the `@read`
decorator.

### Query handlers are synchronous only. { data-toc-label="Synchronous" }

Unlike command and event handlers, query handlers have no async mode, no
stream subscriptions, and no event store involvement. They execute
synchronously and return immediately.

### One handler per query. { data-toc-label="Single Handler" }

Each query can only be handled by one handler method. This mirrors the
command handler constraint and ensures unambiguous routing.

## Best Practices

### Keep handlers thin. { data-toc-label="Thin Handlers" }

Query handlers should delegate to ReadView for data access. They should
transform and filter, not compute or aggregate. Complex read logic belongs
in the projection design, not the handler.

### Use ReadView, not repositories. { data-toc-label="Use ReadView" }

Access projection data through `domain.view_for(Projection)` which
returns a read-only facade. This enforces CQRS separation and prevents
accidental mutations.

### Validate through query fields. { data-toc-label="Query Validation" }

Leverage query field constraints (`required`, `min_value`, `max_value`,
`choices`) for input validation. The query object validates its fields
before reaching the handler.

---

## Next steps

For practical details on defining and using query handlers in Protean, see
the guide:

- [Query Handlers](../../guides/consume-state/query-handlers.md) -- Defining
  handlers, using `@read`, dispatching queries.

For related concepts:

- [Projections](./projections.md) -- The read models that query handlers
  operate on.
- [Command Handlers](./command-handlers.md) -- The write-side counterpart.
