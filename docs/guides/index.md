# Guides

The guides section is your comprehensive reference for building applications
with Protean. Whether you're modeling your first aggregate or architecting an
event-sourced system, you'll find detailed, practical guidance for every
concept and pattern Protean supports.

If you haven't already, start with the
[Tutorial](./getting-started/tutorial/index.md) to build a complete
application from scratch. These guides go deeper into each topic and serve
as a reference you'll return to as your application grows.

## Choose Your Path

Protean supports three architectural approaches — **DDD**, **CQRS**, and
**Event Sourcing** — each building on the one before it. Not sure which
to use? Start with DDD and evolve later.

[:material-arrow-right-box: Compare pathways and choose](./pathways/index.md){ .md-button }

## Browse by Topic

<div class="grid cards" markdown>

-   **:material-shape-outline: Define Your Domain**

    ---

    Model your business concepts with aggregates, entities, value objects,
    and rich behavior.

    [:material-arrow-right-box: Set Up the Domain](./compose-a-domain/index.md) ·
    [:material-arrow-right-box: Define Domain Elements](./domain-definition/index.md) ·
    [:material-arrow-right-box: Add Rules and Behavior](./domain-behavior/index.md)

-   **:material-cog-outline: Change State**

    ---

    Process state changes through application services, commands, and
    command handlers. Persist and retrieve aggregates.

    [:material-arrow-right-box: Change State](./change-state/index.md)

-   **:material-broadcast: React to Changes**

    ---

    Respond to state changes with event handlers, projections, process
    managers, and subscribers.

    [:material-arrow-right-box: React to Changes](./consume-state/index.md)

-   **:material-server-outline: Run in Production**

    ---

    Run the async processing server and integrate with FastAPI.

    [:material-arrow-right-box: Run the Server](./server/index.md) ·
    [:material-arrow-right-box: FastAPI](./fastapi/index.md)

    *See also:* [Configuration](../reference/configuration/index.md) ·
    [CLI](../reference/cli/index.md) ·
    [Adapters](../reference/adapters/index.md)

-   **:material-test-tube: Test Your Application**

    ---

    Strategies for testing every layer of your application.

    [:material-arrow-right-box: Testing](./testing/index.md)

</div>

## How Do I...?

A quick reference for common tasks. See the
[full task index](../how-do-i.md) for more.

| I want to...                          | Go to                                                                 |
|---------------------------------------|-----------------------------------------------------------------------|
| Define an aggregate                   | [Aggregates](./domain-definition/aggregates.md)                       |
| Add a child entity                    | [Entities](./domain-definition/entities.md)                           |
| Enforce business rules                | [Invariants](./domain-behavior/invariants.md)                         |
| Handle a request (synchronous)        | [Application Services](./change-state/application-services.md)        |
| Handle a request (via commands)       | [Commands](./change-state/commands.md) + [Handlers](./change-state/command-handlers.md) |
| Save or load an aggregate             | [Persist](./change-state/persist-aggregates.md) · [Retrieve](./change-state/retrieve-aggregates.md) |
| React to a domain event               | [Event Handlers](./consume-state/event-handlers.md)                   |
| Build a read-optimized view           | [Projections](./consume-state/projections.md)                         |
| Choose between CQRS and ES            | [Architecture Decision](../concepts/architecture/architecture-decision.md)    |
| Use Protean with FastAPI              | [FastAPI Integration](./fastapi/index.md)                             |
| Test my domain logic                  | [Testing](./testing/index.md)                                         |

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
| ES Repositories      |  —  |  —   |  ✓             |
| `@apply` decorator   |  —  |  —   |  ✓             |

✓ = core to this path, — = not used
