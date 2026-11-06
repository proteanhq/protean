# Choose a Path

Protean supports three architectural approaches to building applications.
Protean does not force a single pattern: you pick the right level of
sophistication for your domain. You can change that level over time as your
needs change.

Each approach **builds on the one before it**, so the concepts you learn at
one level carry forward to the next:

1. **[Domain-Driven Design](./ddd.md)**: Model your domain with aggregates,
   application services, and repositories. Events propagate side effects.
   This is the foundation.

2. **[CQRS](./cqrs.md)**: Separate reads from writes with explicit commands,
   command handlers, and read-optimized projections. Builds on everything in
   DDD.

3. **[Event Sourcing](./event-sourcing.md)**: Derive state from event
   replay instead of storing snapshots. Adds full audit trails and temporal
   queries. Builds on everything in CQRS.

!!! tip "Not sure which to pick?"
    Start with **DDD**. It's the simplest path and covers the majority of
    use cases. You can always evolve to CQRS or Event Sourcing later. Protean
    is designed to make that transition smooth. See the [Architecture
    Decision](../../concepts/architecture/architecture-decision.md) guide for a
    systematic framework.

## What a pathway gives you

Each pathway page gives you:

- A brief overview of the architectural approach
- A diagram of the request flow
- The specific Protean elements you'll use
- A **guided reading order** through the existing documentation

The pathway pages are not standalone tutorials. They give you an overview of
the approach and then link you to the detailed guides for each concept. Each
pathway page is a curated reading list for the architecture you choose.

## What Elements Do I Need?

This matrix shows which Protean domain elements are used in each
architectural approach:

| Element              | DDD | CQRS | Event Sourcing |
|----------------------|:---:|:----:|:--------------:|
| Aggregates           |  ✓  |  ✓   |  ✓             |
| Entities             |  ✓  |  ✓   |  ✓             |
| Value Objects        |  ✓  |  ✓   |  ✓             |
| Domain Services      |  ✓  |  ✓   |  ✓             |
| Repositories         |  ✓  |  ✓   |  —             |
| Application Services |  ✓  |  —   |  —             |
| Commands             |  —  |  ✓   |  ✓             |
| Command Handlers     |  —  |  ✓   |  ✓             |
| Events               |  ✓  |  ✓   |  ✓             |
| Event Handlers       |  ✓  |  ✓   |  ✓             |
| Subscribers          |  ✓  |  ✓   |  ✓             |
| Projections          |  —  |  ✓   |  ✓             |
| Projectors           |  —  |  ✓   |  ✓             |
| `@apply` decorator   |  —  |  —   |  ✓             |

✓ = core to this path, = not used
