# Application Services

Application services coordinate use-cases. They sit at the boundary between
the external world — API controllers, CLI commands, background jobs — and the
domain model. An application service receives a request, orchestrates the
necessary [aggregates](./aggregates.md) and
[domain services](./domain-services.md), and returns a result.

Application services are the entry point for the DDD architectural style.
In a pure DDD application (before introducing CQRS), application services
are how external callers trigger domain operations.

## Facts

### Application services are always associated with an aggregate. { data-toc-label="Linked to Aggregate" }

Every application service declares the aggregate it operates on. This
association scopes the service to a single aggregate cluster, keeping the
boundary of responsibility clear.

### Application services orchestrate, not decide. { data-toc-label="Thin Orchestration" }

An application service does not contain business logic. It loads an aggregate,
calls a method on it, and persists the result. The aggregate and domain
services are where rules live. If an application service starts making business
decisions, that logic should be pushed down into the domain model.

### Each use-case method runs within a Unit of Work. { data-toc-label="Transactions" }

Use-case methods are automatically wrapped in a Unit of Work. All aggregate
mutations, [event](./events.md) publications, and persistence operations within
a single use-case are committed as one atomic transaction — or rolled back
entirely if something fails.

### Application services return values synchronously. { data-toc-label="Return Values" }

Unlike [event handlers](./event-handlers.md), application services execute
synchronously and can return results to the caller. This makes them suitable
for request-response interactions where the client needs immediate feedback,
such as returning a newly created resource ID or an authentication token.

### Application services invoke domain logic. { data-toc-label="Invoke Domain Logic" }

The typical flow inside an application service method is:
load the aggregate through a [repository](./repositories.md), call one or more
methods on the aggregate (or pass it to a domain service), and then persist
the result. The application service coordinates; the domain model acts.

### Application services are named after use-cases. { data-toc-label="Use-Case Naming" }

Service and method names should reflect what the business operation achieves —
`place_order`, `register_customer`, `cancel_subscription` — not the technical
mechanism. This keeps the application layer aligned with the
ubiquitous language.

### Application services are replaced by Command Handlers in CQRS. { data-toc-label="CQRS Transition" }

When you evolve to a CQRS architecture, the role of application services is
taken over by [commands](./commands.md) and
[command handlers](./command-handlers.md). The command handler receives a
command DTO, performs the same orchestration an application service would, and
can additionally be invoked asynchronously. Application services remain the
right choice for simpler DDD architectures that do not need the command/query
separation.

## Best Practices

### Keep application services thin. { data-toc-label="Keep Thin" }

If an application service method grows beyond loading, calling, and
persisting, it is likely absorbing domain logic. Extract that logic into the
aggregate or a domain service.

### One use-case per method. { data-toc-label="One Use-Case" }

Each method should represent a single, cohesive business operation. Combining
multiple use-cases into one method makes error handling ambiguous and
transaction boundaries unclear.

### Let the domain model enforce rules. { data-toc-label="Domain Rules" }

Validation and invariant enforcement belong in the aggregate, not the
application service. The application service trusts the domain model to reject
invalid state.

---

## Next steps

For practical details on defining and using application services in Protean, see the guide:

- [Application Services](../../guides/change-state/application-services.md) — Defining services, the @use_case decorator, workflow, return values, and error handling.

For design guidance:

- [Thin Handlers, Rich Domain](../../patterns/thin-handlers-rich-domain.md) — Keeping orchestration layers thin by pushing logic into the domain model.
