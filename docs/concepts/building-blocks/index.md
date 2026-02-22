# Building Blocks

Building blocks are the tactical patterns of Domain-Driven Design — the
concrete elements you use to model, enforce, and evolve business logic in
code. Protean provides a decorator-driven element for each pattern, so you
can focus on domain semantics rather than infrastructure plumbing.

The elements are organized into four layers, each with a distinct
responsibility.

```mermaid
graph TB
    subgraph EXT["External World"]
        API["API / CLI / Job"]
        Broker["Message Broker"]
    end

    subgraph APP["Application Layer"]
        AS["Application Service"]
        Cmd["Command"]
        CH["Command Handler"]
    end

    subgraph DOM["Domain Model"]
        Agg["Aggregate"]
        Ent["Entity"]
        VO["Value Object"]
        DS["Domain Service"]
    end

    subgraph REACT["Reactive Layer"]
        Evt["Event"]
        EH["Event Handler"]
        PM["Process Manager"]
        Proj["Projection"]
        Pjr["Projector"]
        Sub["Subscriber"]
    end

    subgraph PERSIST["Persistence"]
        Repo["Repository"]
    end

    API -->|"use case"| AS
    API -->|"submit"| Cmd
    Cmd -->|"handled by"| CH

    AS -->|"invoke"| Agg
    AS -->|"invoke"| DS
    CH -->|"invoke"| Agg

    Agg -->|"contains"| Ent
    Agg -->|"contains"| VO
    DS -->|"operates on"| Agg

    Agg -->|"raises"| Evt
    Evt -->|"consumed by"| EH
    Evt -->|"consumed by"| PM
    Evt -->|"consumed by"| Pjr
    Pjr -->|"maintains"| Proj

    Broker -->|"delivers to"| Sub
    Sub -->|"triggers"| Agg

    Repo -->|"persists"| Agg

    EH -->|"modifies"| Agg
    PM -->|"issues"| Cmd

    style EXT fill:#f5f5f5,stroke:#9e9e9e
    style APP fill:#e3f2fd,stroke:#1e88e5
    style DOM fill:#e8f5e9,stroke:#43a047
    style REACT fill:#fff3e0,stroke:#fb8c00
    style PERSIST fill:#f3e5f5,stroke:#8e24aa
```

## Domain Model

The domain model is the heart of the system. It captures the essential
complexity of the business in code — the concepts, rules, and relationships
that give the software its reason to exist.

| Element | Purpose |
|---------|---------|
| [Aggregate](./aggregates.md) | Root entity and transaction boundary for a cluster of objects |
| [Entity](./entities.md) | Object with unique identity, always accessed through its aggregate |
| [Value Object](./value-objects.md) | Immutable, identity-less object defined entirely by its attributes |
| [Domain Service](./domain-services.md) | Stateless operation that spans multiple aggregates |

## Application Layer

The application layer sits between the external world and the domain model.
It translates intentions into domain operations without containing business
logic itself.

| Element | Purpose |
|---------|---------|
| [Application Service](./application-services.md) | Coordinates a use-case by orchestrating aggregates and domain services |
| [Command](./commands.md) | Immutable DTO expressing an intent to change state |
| [Command Handler](./command-handlers.md) | Receives a command, loads the aggregate, invokes domain logic, and persists |

## Reactive Layer

The reactive layer responds to things that have already happened. It
propagates state changes, maintains read models, and bridges to external
systems — all without coupling back to the code that produced the original
change.

| Element | Purpose |
|---------|---------|
| [Event](./events.md) | Immutable fact recording a state change in the domain |
| [Event Handler](./event-handlers.md) | Reacts to domain events with side effects and cross-aggregate coordination |
| [Process Manager](./process-managers.md) | Stateful coordinator for multi-step processes spanning multiple aggregates |
| [Projection](./projections.md) | Read-optimized, denormalized view of domain data |
| [Projector](./projectors.md) | Specialized handler that keeps a projection in sync with domain events |
| [Subscriber](./subscribers.md) | Consumes messages from an external message broker |

## Persistence

Persistence elements decouple the domain model from storage technology,
so aggregates remain ignorant of how and where they are stored.

| Element | Purpose |
|---------|---------|
| [Repository](./repositories.md) | Collection-oriented interface to persist and retrieve aggregates |
