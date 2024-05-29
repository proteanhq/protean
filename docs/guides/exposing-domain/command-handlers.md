# Command Handlers

Command handlers are responsible for executing commands and persisting system
state. They typically interact with aggregate roots to perform the required
operations, ensuring that all business rules and invariants are upheld.

## Key Facts

- Command Handlers extract relevant data from a command and invoke the
appropriate aggregate method with the necessary parameters.
- Command Handlers are responsible for hydrating (loading) and persisting
aggregates.
- A Command Handler method can hydrate more than one aggregate at a time,
depending on the business process requirements, but it should always persist
one aggregate root. Other aggregates should be synced eventually through
domain events.

## Defining a Command Handler

Command Handlers are defined with the `Domain.command_handler` decorator:

```python hl_lines="19-22 46-52"
{! docs_src/guides/exposing-domain/002.py !}
```

## Workflow

```mermaid
sequenceDiagram
  autonumber
  Domain->>Command Handler: Command object
  Command Handler->>Command Handler: Load aggregate
  Command Handler->>Aggregate: Extract data and invoke method
  Aggregate->>Aggregate: Mutate
  Aggregate-->>Command Handler: 
  Command Handler->>Command Handler: Persist aggregate
```

1. **Domain Sends Command Object to Command Handler**: The domain layer
initiates the process by sending a command object to the command handler.
This command object encapsulates the intent to perform a specific action or
operation within the domain.

1. **Command Handler Loads Aggregate**: Upon receiving the command object, the
command handler begins by loading the necessary aggregate from the repository
or data store. The aggregate is the key entity that will be acted upon based
on the command.

1. **Command Handler Extracts Data and Invokes Aggregate Method**: The command
handler extracts the relevant data from the command object and invokes the
appropriate method on the aggregate. This method call triggers the aggregate
to perform the specified operation.

1. **Aggregate Mutates**: Within the aggregate, the invoked method processes
the data and performs the necessary business logic, resulting in a change
(mutation) of the aggregate's state. This ensures that the operation adheres
to the business rules and maintains consistency.

1. **Aggregate Responds to Command Handler**: After mutating its state, the
aggregate completes its operation and returns control to the command handler.
The response may include confirmation of the successful operation or any
relevant data resulting from the mutation.

1. **Command Handler Persists Aggregate**: Finally, the command handler
persists the modified aggregate back to the repository or data store. This
ensures that the changes made to the aggregate's state are saved and reflected
in the system's state.

## Unit of Work

Command handler methods always execute within a `UnitOfWork` context by
default. The UnitOfWork pattern ensures that the series of changes to an
aggregate cluster are treated as a single, atomic transaction. If an error
occurs, the UnitOfWork rolls back all changes, ensuring no partial updates
are applied.

Each command handler method is wrapped in a `UnitOfWork` context, without
having to explicitly specify it. Both handler methods in
`AccountCommandHandler` below are equivalent:

```python hl_lines="5"
@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(RegisterCommand)
    def register(self, command: RegisterCommand):
        with UnitOfWork():
            ...  # code to register account
    
    @handle(ActivateCommand)
    def activate(self, command: ActivateCommand):
        ...  # code to activate account
```

!!!note
    A `UnitOfWork` context applies to objects in the aggregate cluster,
    and not multiple aggregates. A Command Handler method can load multiple
    aggregates to perform the business process, but should never persist more
    than one at a time. Other aggregates should be synced eventually through
    domain events.