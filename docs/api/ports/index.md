# Ports

Abstract interface contracts for infrastructure adapters. Ports define the
boundary between the domain and external infrastructure.

For concrete adapter documentation, see
[Adapters Reference](../../reference/adapters/index.md).

<div class="grid cards" markdown>

-   **:material-database: DatabasePort**

    ---

    Database provider interface for persistence adapters.

    [:material-arrow-right-box: DatabasePort](database.md)

-   **:material-message-flash: BrokerPort**

    ---

    Message broker interface for event distribution.

    [:material-arrow-right-box: BrokerPort](broker.md)

-   **:material-history: EventStorePort**

    ---

    Event store interface for event-sourced persistence, with the
    `BaseEventStore` class that event store adapters extend.

    [:material-arrow-right-box: EventStorePort](event-store.md)

-   **:material-cached: CachePort**

    ---

    Cache interface for read-optimized storage.

    [:material-arrow-right-box: CachePort](cache.md)

</div>
