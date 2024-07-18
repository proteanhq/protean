# Commands

Commands are data transfer objects that express an intention to change the
state of the system. They represent actions that a user or system wants to
perform. In DDD, commands are an essential part of the application layer,
where they help to encapsulate and convey user intentions.

Commands typically do not return values; instead, they result in events that
indicate changes in the system.

## Facts

### Commands express intentions. { data-toc-label="Intentions" }
Commands are not queries; they do not request data but rather express an
intention to perform an action that changes the state of the system.

### Commands are essentially Data Transfer Objects (DTO). { data-toc-label="Data Transfer Objects" }
They can only hold simple fields and Value Objects.

### Commands are immutable. { data-toc-label="Immutability" }
Commands should be designed to be immutable once created. This ensures that the intention they represent cannot be altered after they are sent.

### Commands trigger domain logic. { data-toc-label="Domain Logic" }
Commands are handled by application services or command handlers, which then
interact with the domain model to execute the intended action.

### Commands are named with verbs. { data-toc-label="Naming" }
Commands should be named clearly and concisely, typically using verbs to
indicate the action to be performed, such as `CreateOrder`,
`UpdateCustomerInfo`, or `CancelReservation`. These terms should match with
concepts in Ubiquitous Language.

## Structure

### Commands have **metadata**. { data-toc-label="Metadata" }
Headers and metadata such as timestamps, unique identifiers, and version
numbers are included in commands for precise tracking of origin and intent.

### Commands are **versioned**. { data-toc-label="Versioning" }
Each command is assigned a version number, ensuring that commands can evolve
over time. Since commands are handled by a single aggregate through a command
handler, there is seldom a need to support multile versions of commands at
the same time.

### Commands are **timestamped**. { data-toc-label="Timestamp" }
Each command carries a timestamp indicating when the command was initiated,
which is crucial for processing incoming commands chronologically.

### Commands are written into streams.  { data-toc-label="Command Streams" }
Commands are written to and read from streams. Review the section on
[Streams](../streams.md) for a deep-dive.

### Command objects are always valid. { data-toc-label="Validation" }
Like other elements in Protean, commands are validated as soon as they are
initialized to ensure they contain all required information and that the data
is in the correct format.

## Persistence

### Commands do not persist data directly. { data-toc-label="Persistence" }
Commands themselves do not persist data; they trigger domain operations that
result in changes to the state of aggregates, which are then persisted by
repositories.

### Commands can result in events. { data-toc-label="Events" }
Once a command has been successfully handled, it may result in domain events
being published. These events can then be used to notify other parts of the
system about the changes.

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
transmitted over a network. Ensure that appropriate security measures are in
place to protect this data.
