# Command Handlers

When a [command](./commands.md) arrives, your application needs to orchestrate
the response: load the right aggregate, invoke the domain method, persist the
result, and handle errors. If the API controller did this orchestration, the
controller would mix domain logic into infrastructure code. If the aggregate
did this orchestration, the aggregate would need to know about persistence.

Command handlers take this orchestration out of both the API controller and the
aggregate by acting as thin orchestrators. They receive a command, coordinate
the necessary steps, and delegate all business logic to the aggregate. The
handler itself contains no business rules.

## Facts

### Command handlers are connected to an aggregate. { data-toc-label="Connected to Aggregate" }

Command handlers are always connected to a single aggregate. One command handler
per aggregate is the norm, with all aggregate commands handled within it.

### A Command handler contains multiple handlers. { data-toc-label="Handlers" }

Each method in a command handler is connected to one specific command and
processes that command.

### Handlers are single-purpose. { data-toc-label="Single-Purpose" }

Each handler method is responsible for handling a single type of command. With
one command type per method, you keep the command handling logic focused and
manageable.

### Handlers should deal only with the associated aggregate. { data-toc-label="Single Aggregate" }

Methods in a command handler should only deal with managing the lifecycle of
the aggregate associated with it. Any state change beyond an aggregate's
boundary should be performed by eventual consistency mechanisms, like raising
an [event](./events.md) and consuming it in the
[event handler](./event-handlers.md) of the other aggregate.

### Command handlers invoke domain logic. { data-toc-label="Invoke Domain Logic" }

Command handlers do not contain business logic themselves. Instead, they invoke
methods on [aggregates](./aggregates.md) or
[domain services](./domain-services.md) to perform the necessary actions.

### Command handlers coordinate actions. { data-toc-label="Coordinate Actions" }

Command handlers coordinate multiple actions related to each command.
Primarily, a command handler hydrates (fetches) the aggregate, invokes methods
that change its state and persists the changes through a
[repository](./repositories.md).

### Command handlers can return values. { data-toc-label="Return Values" }

When processed synchronously, command handlers can return values to the caller.
You can use a return value to send back a token after authentication, or the ID
of a newly created resource.

A single event can have multiple [event handlers](./event-handlers.md), and
they don't return values. A command has only one handler, so that handler can
pass its return value back to the caller. This is consistent with the command
pattern, where a command represents an intent to perform an action and may need
to provide immediate feedback.

By default, command handlers return the position of the command in the command stream back to the caller.

### Handler methods are enclosed in Unit of Work context. { data-toc-label="Unit of Work"}

Each handler method is automatically enclosed within a Unit of Work context.
This means that all interactions with the infrastructure is packaged into a
single transaction. This makes it all the more important to not mix multiple
responsibilities or aggregates when handling a command.

### Commands can be handled asynchronously. { data-toc-label="Asynchronous" }

Synchronous command handling is the norm because it preserves data integrity.
For performance reasons, you can configure the domain to handle commands
asynchronously.

## Best Practices

### Ensure idempotency. { data-toc-label="Idempotency" }

Command handling should be idempotent, meaning that handling the same command
multiple times should not produce unintended side effects. This can be achieved
by checking the current state before applying changes.

### Handle exceptions gracefully. { data-toc-label="Exception Handling" }

When an exception occurs, a command handler should perform any necessary
rollback actions. The command handler should also return meaningful error
messages to the caller.

### Validate commands. { data-toc-label="Validation" }

Make sure that commands are validated before processing. This can be done in a
separate validation layer or within the command handler itself.

### Return values only when necessary. { data-toc-label="Return Values" }

Only return values from command handlers when they are genuinely needed by the caller.
For example, return authentication tokens or newly created resource IDs, but not entire
entity representations. Return values should be small and relevant to the immediate needs
of the caller.

---

## Next steps

For practical details on defining and using command handlers in Protean, see the guide:

- [Command Handlers](../../guides/change-state/command-handlers.md): Defining handlers, workflow, return values, idempotency, and error handling.

For the read-side counterpart:

- [Query Handlers](./query-handlers.md): Processing structured read intents from projections (the read side of CQRS).

For design guidance:

- [Application Service vs Command Handler](../../patterns/application-service-vs-command-handler.md): When to use which, with decision tree and comparison table.
- [Thin Handlers, Rich Domain](../../patterns/thin-handlers-rich-domain.md): Keeping handlers thin by pushing logic into the domain model.
- [Command Idempotency](../../patterns/command-idempotency.md): Handling duplicate commands safely.
