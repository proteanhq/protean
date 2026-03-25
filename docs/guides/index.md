# Guides

Goal-oriented guides for building applications with Protean. Each guide
covers a specific task with practical code examples.

If you haven't already, start with
[Hello, Protean!](./getting-started/hello.md) for a quick first taste, then
work through the [Tutorial](./getting-started/tutorial/index.md) to build a
complete application from scratch. These guides go deeper into each topic and
serve as a reference you'll return to as your application grows.

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
    [:material-arrow-right-box: FastAPI](./fastapi/index.md) ·
    [:material-arrow-right-box: Observability](./observability/correlation-and-causation.md)

    *See also:* [Configuration](../reference/configuration/index.md) ·
    [CLI](../reference/cli/index.md) ·
    [Adapters](../reference/adapters/index.md)

-   **:material-test-tube: Test Your Application**

    ---

    Strategies for testing every layer of your application.

    [:material-arrow-right-box: Testing](./testing/index.md)

</div>

## How Do I...?

For the full task index, see [How Do I...?](../how-do-i.md).
