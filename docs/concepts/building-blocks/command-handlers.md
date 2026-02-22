# Command Handlers

Command handlers are responsible for processing commands. They encapsulate the
logic required to handle a command and ensure that the appropriate actions are
taken within the domain model.

Command handlers typically reside in the application layer and serve as a
bridge between the application's API and the domain model.

## Facts

### Command handlers are connected to an aggregate. { data-toc-label="Connected to Aggregate" }

Command handlers are always connected to a single aggregate. One command handler
per aggregate is the norm, with all aggregate commands handled within it.

### A Command handler contains multiple handlers. { data-toc-label="Handlers" }

Each method in a command handler is connected to a specific command to handle
and process.

### Handlers are single-purpose. { data-toc-label="Single-Purpose" }

Each handler method is responsible for handling a single type of command. This
ensures that the command handling logic is focused and manageable.

### Handlers should deal only with the associated aggregate. { data-toc-label="Single Aggregate" }

Methods in a command handler should only deal with managing the lifecycle of
the aggregate associated with it. Any state change beyong an aggregate's
boundary should be performed by eventual consistency mechanisms, like raising
an [event](./events.md) and consuming it in the
[event handler](./event-handlers.md) of the other aggregate.

### Command handlers invoke domain logic. { data-toc-label="Invoke Domain Logic" }

Command handlers do not contain business logic themselves. Instead, they invoke
methods on [aggregates](./aggregates.md) or
[domain services](./domain-services.md) to perform the necessary actions.

### Command handlers coordinate actions. { data-toc-label="Coordinate Actions" }

Command handlers coordinate multiple actions related to each command. Primarily,
this involves hydrating (fetching) the aggregate, invoking methods to perform
state changes and persisting changes through a
[repository](./repositories.md).

### Command handlers can return values. { data-toc-label="Return Values" }

When processed synchronously, command handlers can return values to the caller. This
is useful for scenarios like authentication where you need to return a token, or when
you need to return the ID of a newly created resource.

Unlike [event handlers](./event-handlers.md) (which can have multiple handlers
for a single event and don't return values), a command can only be handled by
a single handler, allowing the return value to be passed back to the caller.
This is consistent with the command pattern, where a command represents an intent to perform an action
and may need to provide immediate feedback.

By default, command handlers return the position of the command in the command stream back to the caller.

### Handler methdos are enclosed in Unit of Work context. { data-toc-label="Unit of Work"}

Each handler method is automatically enclosed within a Unit of Work context.
This means that all interactions with the infrastructure is packaged into a
single transaction. This makes it all the more important to not mix multiple
responsibilities or aggregates when handling a command.

### Commands can be handled asynchronously. { data-toc-label="Asynchronous" }

While handling commands synchronously is the norm to preserve data integrity,
it is possible to configure the domain to handle commands asynchronously for
performance reasons.

## Best Practices

### Ensure idempotency. { data-toc-label="Idempotency" }

Command handling should be idempotent, meaning that handling the same command
multiple times should not produce unintended side effects. This can be achieved
by checking the current state before applying changes.

### Handle exceptions gracefully. { data-toc-label="Exception Handling" }

Command handlers should handle exceptions gracefully, ensuring that any
necessary rollback actions are performed and that meaningful error messages are
returned to the caller.

### Validate commands. { data-toc-label="Validation" }

Ensure that commands are validated before processing. This can be done in a
separate validation layer or within the command handler itself.

### Return values only when necessary. { data-toc-label="Return Values" }

Only return values from command handlers when they are genuinely needed by the caller.
For example, return authentication tokens or newly created resource IDs, but not entire
entity representations. Return values should be small and relevant to the immediate needs
of the caller.

---

## Next steps

For practical details on defining and using command handlers in Protean, see the guide:

- [Command Handlers](../../guides/change-state/command-handlers.md) — Defining handlers, workflow, return values, idempotency, and error handling.

For design guidance:

- [Thin Handlers, Rich Domain](../../patterns/thin-handlers-rich-domain.md) — Keeping handlers thin by pushing logic into the domain model.
- [Command Idempotency](../../patterns/command-idempotency.md) — Handling duplicate commands safely.
