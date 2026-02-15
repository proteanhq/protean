# Changing state

In the [core concept on Changing State](../../core-concepts/changing-state.md),
we discussed the workflow and thought process on how to accept state change
requests and process them.

In this section, we dive deeper into concrete implementations of the
application layer.

- [Application Services](./application-services.md) -- Bridge between the API layer and the domain model.
- [Commands](./commands.md) -- Data transfer objects expressing intent to change state.
- [Command Handlers](./command-handlers.md) -- Process commands and execute domain logic.
- [Repositories](./repositories.md) -- Collection-oriented persistence abstraction for aggregates.
- [Persist Aggregates](./persist-aggregates.md) -- Save aggregates using a repository's `add` method.
- [Retrieve Aggregates](./retrieve-aggregates.md) -- Load and query aggregates using QuerySets, filters, and Q objects.
