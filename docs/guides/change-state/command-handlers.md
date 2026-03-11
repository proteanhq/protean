# Command Handlers

<span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Commands carry intent, but someone needs to act on them. Command handlers are
the "doers" — they receive a command, load the right aggregate, call the
appropriate domain method, and persist the result. They keep your aggregates
free of infrastructure concerns and your API layer free of domain logic.

For background on how command handlers fit the CQRS architecture, see
[Command Handlers concept](../../concepts/building-blocks/command-handlers.md).

## Defining a Command Handler

Command Handlers are defined with the `Domain.command_handler` decorator:

```python hl_lines="20-23 47-53"
--8<-- "guides/change-state/007.py:full"
```

### Decorator options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `part_of` | class or string | *required* | The aggregate this handler processes commands for. |
| `stream_category` | `str` | derived from `part_of` | Read-only. Always derived from the aggregate's stream category. Cannot be overridden. |

### The `@handle` decorator

Each method that processes a command is decorated with `@handle`, imported from
`protean`:

```python
from protean import handle
```

`@handle(CommandClass)` registers the method as the handler for that command
type. It also wraps the method body in a [Unit of Work](./unit-of-work.md),
providing automatic transaction management. A single command can only be
handled by one handler method across the entire domain — Protean enforces
one-handler-per-command.

### How routing works

When you call `domain.process(command)`, Protean uses the command's `part_of`
aggregate to find the registered command handler for that aggregate. It then
looks up the `@handle`-decorated method that matches the command's type and
invokes it. You never need to wire this routing manually — it is all derived
from the `part_of` associations on the command and command handler.

### Stream Category {#stream-category}

Command handlers automatically subscribe to commands in their associated aggregate's [stream category](../../concepts/async-processing/stream-categories.md). When a command is processed, it is routed to the appropriate handler based on the command's target aggregate and its stream category.

For example, if an `Order` aggregate has a stream category of `order`, its command handler will listen for commands on the `order:command` stream category. Commands are stored in streams following the pattern `<domain>::<stream_category>-<aggregate_id>`.

Unlike event handlers, command handlers **cannot** override their stream category. The stream category is always derived from the `part_of` aggregate. This ensures that commands are always routed to the single handler responsible for the target aggregate.

Learn more about stream categories and message routing in the [Stream Categories](../../concepts/async-processing/stream-categories.md) guide.

??? info "Internal workflow"

    ```mermaid
    sequenceDiagram
      autonumber
      App->>Domain: domain.process(command)
      Domain->>Event Store: Store command
      Domain->>Command Handler: Dispatch command
      Command Handler->>Command Handler: Extract data and Load aggregate
      Command Handler->>Aggregate: Invoke method
      Aggregate->>Aggregate: Mutate
      Aggregate-->>Command Handler: Done
      Command Handler->>Command Handler: Persist aggregate
    ```

    1. **Application Submits Command**: The application calls `domain.process(command)`,
    which enriches the command with metadata and writes it to the event store.

    1. **Command is Stored**: The command is persisted to the event store before any
    processing occurs, ensuring an audit trail exists even if the handler fails.

    1. **Domain Dispatches to Handler**: The domain identifies the correct command
    handler based on the command's `part_of` aggregate and dispatches it.

    1. **Command Handler Loads Aggregate**: The command handler loads the target
    aggregate from the repository using `current_domain.repository_for()`.

    1. **Aggregate Mutates**: The handler invokes the appropriate method on the
    aggregate, which applies business rules, validates invariants, and changes
    its internal state.

    1. **Command Handler Persists Aggregate**: The handler persists the modified
    aggregate back to the repository, committing changes within the Unit of Work.

## Return Values from Command Handlers

Command handlers can optionally return values to the caller when processed synchronously. This behavior is determined by how the command is processed by the domain.

### Synchronous Processing

When commands are processed synchronously, the command handler's return value is passed back to the caller. This is useful for:

- Returning newly created resource identifiers
- Providing validation or processing results
- Returning calculated values or status information

To process a command synchronously and receive its return value:

```python
# Process command synchronously and get the return value
result = domain.process(command, asynchronous=False)
```

Example of a command handler that returns a value:

```python
@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(RegisterCommand)
    def register(self, command: RegisterCommand) -> str:
        account = Account(
            email=command.email,
            name=command.name
        )
        current_domain.repository_for(Account).add(account)

        # Return the account ID for immediate use
        return account.id
```

### Asynchronous Processing

When commands are processed asynchronously (the default behavior), the command handler's return value is not passed back to the caller. Instead, the domain's `process` method returns the position of the command in the event store:

```python
# Process command asynchronously (default)
position = domain.process(command)  # or domain.process(command, asynchronous=True)
```

In asynchronous processing, commands are handled in the background by the Protean Engine, and any return values from the command handler are ignored.

### Configuring Default Processing Behavior

The default command processing behavior can be configured in the domain's configuration:

```toml
# ...
command_processing = "sync"  # or "async"
# ...
```

When set to "sync", all commands will be processed synchronously by default unless explicitly specified as asynchronous, and vice versa.

## Idempotency in Handlers

When a command is submitted with an idempotency key (via
`domain.process(command, idempotency_key="...")`), the key is available in the
handler through the command's metadata:

```python
@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(ChargeCard)
    def charge(self, command: ChargeCard):
        key = command._metadata.headers.idempotency_key

        # Pass through to external APIs that support idempotency
        stripe.PaymentIntent.create(
            amount=command.amount,
            currency="usd",
            idempotency_key=key,
        )
```

This is useful for:

- **Pass-through to external APIs**: Many services (Stripe, payment processors)
  accept idempotency keys natively. Passing the same key ensures end-to-end
  retry safety.
- **Handler-level deduplication**: For additive operations (incrementing
  counters, adding items), the handler can check the key against a set of
  previously processed keys stored on the aggregate.

For detailed patterns including natural idempotency, check-then-act, and
event-sourced aggregate strategies, see the
[Command Idempotency](../../patterns/command-idempotency.md) pattern guide.

## Unit of Work

Each command handler method runs within a `UnitOfWork` context — if the method
completes successfully, all changes are committed; if an exception is raised,
everything is rolled back.

For details on how the Unit of Work pattern works, see the
[Unit of Work](unit-of-work.md) guide.

!!!note
    A `UnitOfWork` context applies to objects in the aggregate cluster,
    and not multiple aggregates. A Command Handler method can load multiple
    aggregates to perform the business process, but should never persist more
    than one at a time. Other aggregates should be synced eventually through
    domain events.

## Error Handling

Error handling differs between synchronous and asynchronous command processing:

- **Synchronous** (`asynchronous=False`): Exceptions raised in the handler
  propagate directly to the caller (the code that called `domain.process()`).
  The UoW is rolled back automatically. There is no `handle_error` hook —
  the caller is responsible for catching and handling the exception.

- **Asynchronous** (default): The Protean Engine catches exceptions during
  background processing and invokes the handler's `handle_error` class method
  (if defined). The engine then continues processing the next command. Since
  there is no caller waiting for a response, the `handle_error` hook is the
  only mechanism for custom error recovery.

### The `handle_error` Method

You can define a `handle_error` class method in your command handler to handle exceptions:

```python
@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(RegisterCommand)
    def register(self, command: RegisterCommand):
        # Command handling logic that might raise exceptions
        ...

    @classmethod
    def handle_error(cls, exc: Exception, message):
        """Custom error handling logic for command processing failures"""
        # Log the error
        logger.error(f"Failed to process command: {exc}")

        # Perform recovery operations
        # Example: notify monitoring systems, attempt retry, etc.
        ...
```

### How It Works

1. When an exception occurs in a command handler method, the Protean Engine catches it.
2. The engine logs detailed error information including stack traces.
3. The engine calls the command handler's `handle_error` method, passing:
   - The original exception that was raised
   - The command message being processed when the exception occurred
4. After `handle_error` returns, processing continues with the next command.

### Handling Errors in the Error Handler

If an exception occurs within the `handle_error` method itself, the Protean Engine will catch that exception too, log it, and continue processing. This ensures that even failures in error handling don't crash the system.

```python
@classmethod
def handle_error(cls, exc: Exception, message):
    try:
        # Potentially risky error handling logic
        ...
    except Exception as error_exc:
        # This secondary exception will be caught by the engine
        logger.error(f"Error in error handler: {error_exc}")
        # The engine will continue processing regardless
```

### Best Practices

1. Make error handlers robust and avoid complex logic that might fail.
2. Use error handlers for logging, notification, and simple recovery.
3. Don't throw exceptions from error handlers unless absolutely necessary.
4. Consider implementing retry logic for transient failures.

## Testing Command Handlers

The simplest way to test a command handler is to submit a command
synchronously and verify the resulting state:

```python
def test_publish_article(test_domain):
    # Arrange
    article = Article(article_id="1", status="DRAFT")
    test_domain.repository_for(Article).add(article)

    # Act
    test_domain.process(
        PublishArticle(article_id="1"),
        asynchronous=False,
    )

    # Assert
    refreshed = test_domain.repository_for(Article).get("1")
    assert refreshed.status == "PUBLISHED"
```

Key points:

- Use `asynchronous=False` to process the command synchronously in tests, so
  the handler runs immediately and you can assert on the result.
- Configure `command_processing = "sync"` in your test domain config to make
  this the default for all tests.
- You can also test return values directly:
  `result = test_domain.process(cmd, asynchronous=False)`.

---

!!! tip "See also"
    **Concept overview:** [Command Handlers](../../concepts/building-blocks/command-handlers.md) — The role of command handlers in processing commands and persisting state.

    **Related guides:**

    - [Commands](./commands.md) — Defining commands and submitting them for processing.
    - [Repositories](./repositories.md) — Persisting and retrieving aggregates.
    - [Application Services](./application-services.md) — An alternative to command handlers for synchronous use cases.
    - [Unit of Work](./unit-of-work.md) — Transaction management and commit lifecycle.

    **Patterns:**

    - [Application Service vs Command Handler](../../patterns/application-service-vs-command-handler.md) — When to use which, with decision tree and comparison table.
    - [Thin Handlers, Rich Domain](../../patterns/thin-handlers-rich-domain.md) — Keeping handlers thin by pushing logic into the domain model.
    - [Command Idempotency](../../patterns/command-idempotency.md) — Handling duplicate commands safely.
