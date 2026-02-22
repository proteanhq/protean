# Change State

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


Protean provides two paths for changing state: directly through Application Services (in the DDD approach) or through Commands and Command Handlers (in CQRS and Event Sourcing). Both paths ultimately load an aggregate, invoke domain methods, and persist the result.

## Process Requests

The request processing pipeline handles incoming intentions to change state, whether from API endpoints, CLI commands, or background jobs.

### Application Services

Application services coordinate use cases by orchestrating aggregates and domain services. They bridge the gap between the external world and the domain model.

[Learn more about application services →](./application-services.md)

### Commands

Commands are immutable data transfer objects expressing an intent to change state. They carry the data needed for a specific operation without containing any logic.

[Learn more about commands →](./commands.md)

### Command Handlers

Command handlers receive commands, load the relevant aggregate, invoke domain methods, and persist the result. Each handler processes a specific command type.

[Learn more about command handlers →](./command-handlers.md)

## Persist Data

Once state has been changed through domain methods, it needs to be persisted. Protean provides a collection-oriented persistence abstraction.

### Repositories

Repositories are the persistence abstraction for aggregates. They provide a collection-like interface for adding, retrieving, and removing aggregates.

[Learn more about repositories →](./repositories.md)

### Persist Aggregates

Save aggregates through a repository's `add` method, with automatic transaction management via the Unit of Work pattern.

[Learn more about persisting aggregates →](./persist-aggregates.md)

### Retrieve Aggregates

Load and query aggregates using QuerySets, filters, Q objects, and lookup expressions.

[Learn more about retrieving aggregates →](./retrieve-aggregates.md)

### Temporal Queries

Reconstitute event-sourced aggregates at a specific version or point in time, enabling time-travel over the full event history.

[Learn more about temporal queries →](./temporal-queries.md)

### Unit of Work

The Unit of Work pattern provides automatic transaction management, ensuring that all changes within a single operation are committed or rolled back together.

[Learn more about the Unit of Work →](./unit-of-work.md)
