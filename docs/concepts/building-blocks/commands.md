# Commands

In most applications, one piece of code *requests* a change (an API controller,
a background job, a saga). A different piece of code *performs* the change (the
domain model). A command carries the caller's intent from one to the other as
an explicit, immutable data object. You can validate, serialize, route, retry,
and audit that object. All before any business logic runs.

Commands and [events](./events.md) are complementary halves of a message-driven
architecture. They differ in tense and semantics:

| | Command | Event |
|---|---------|-------|
| **Tense** | Imperative, *do this* | Past tense, *this happened* |
| **Meaning** | An intent that may be rejected | A fact that has already occurred |
| **Naming** | `PlaceOrder`, `CancelReservation` | `OrderPlaced`, `ReservationCancelled` |
| **Consumers** | Exactly one command handler | Zero or more event handlers |
| **Outcome** | May succeed or fail | Always represents committed state |

## Facts

### Commands express intentions. { data-toc-label="Intentions" }
Commands are not queries and do not request data. A command expresses an
intention to perform an action that changes the state of the system.

### Commands are essentially Data Transfer Objects (DTO). { data-toc-label="Data Transfer Objects" }
They can only hold simple fields and Value Objects.

### Commands are immutable. { data-toc-label="Immutability" }
Commands should be designed to be immutable once created. This ensures that the intention they represent cannot be altered after they are sent.

### Commands trigger domain logic. { data-toc-label="Domain Logic" }
Commands are processed by [command handlers](./command-handlers.md), which
interact with the domain model to execute the intended action.

### Commands are named with verbs. { data-toc-label="Naming" }
Commands should be named clearly and concisely, typically using verbs to
indicate the action to be performed, such as `CreateOrder`,
`UpdateCustomerInfo`, or `CancelReservation`. These terms should match with
concepts in Ubiquitous Language.

## Structure

### Commands have **metadata**. { data-toc-label="Metadata" }
Protean includes headers and metadata in each command, such as timestamps,
unique identifiers, and version numbers, so you can track its origin and intent
precisely.

### Commands are **versioned**. { data-toc-label="Versioning" }
Protean assigns each command a version number (defaulting to `1`), so commands
can evolve over time. Set `__version__` on the class to override:

```python hl_lines="8"
--8<-- "concepts/building-blocks/commands/001.py:versioned"
```

Since commands are handled by a single aggregate through a command handler,
there is seldom a need to support multiple versions of commands at the same
time.

### Commands are **timestamped**. { data-toc-label="Timestamp" }
Each command carries a timestamp of when it was initiated. You need this
timestamp to process incoming commands in chronological order.

### Commands are written into streams.  { data-toc-label="Command Streams" }
Commands are written to and read from streams. Review the section on
[Streams](../foundations/streams.md) for a detailed explanation.

### Command objects are always valid. { data-toc-label="Validation" }
Like other elements in Protean, a command is validated as soon as you
initialize it. Protean checks that the command contains all required
information and that its data is in the correct format.

## Persistence

### Commands do not persist data directly. { data-toc-label="Persistence" }
Commands themselves do not persist data but trigger domain operations that
change the state of aggregates. Repositories then persist those aggregates.

### Commands can result in events. { data-toc-label="Events" }
Once a command has been successfully handled, it may result in domain events
being published. Event handlers in other parts of the system can then consume
these events to learn about the changes.

## Best Practices

### Keep commands simple. { data-toc-label="Simplicity" }
Commands should be simple and focused on a single responsibility. This makes
them easier to understand and maintain.

### Use a consistent naming convention. { data-toc-label="Consistency" }
Maintain a consistent naming convention for commands to ensure clarity and
uniformity across the system.

### Ensure idempotency. { data-toc-label="Idempotency" }
Command handling should be idempotent, meaning that handling the same command
multiple times should result in the same state without unintended side effects.

### Secure sensitive data. { data-toc-label="Security" }
Be mindful of sensitive data within commands, especially when they are
transmitted over a network. Make sure that appropriate security measures are in
place to protect this data.

---

## Next steps

For practical details on defining and processing commands in Protean, see the guide:

- [Commands](../../guides/change-state/commands.md): Defining commands, submitting them, idempotency, and processing modes.

For design guidance:

- [Command Idempotency](../../patterns/command-idempotency.md): Ensuring commands can be safely retried without side effects.
