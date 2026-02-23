# Ports

Abstract interface contracts for infrastructure adapters. Ports define the
boundary between the domain and external infrastructure.

For concrete adapter documentation, see
[Adapters Reference](../../reference/adapters/index.md).

<div class="grid cards" markdown>

-   **:material-database: BaseProvider**

    ---

    Database provider interface for persistence adapters.

    [:material-arrow-right-box: BaseProvider](provider.md)

-   **:material-message-flash: BaseBroker**

    ---

    Message broker interface for event distribution.

    [:material-arrow-right-box: BaseBroker](broker.md)

-   **:material-history: BaseEventStore**

    ---

    Event store interface for event-sourced persistence.

    [:material-arrow-right-box: BaseEventStore](event-store.md)

-   **:material-cached: BaseCache**

    ---

    Cache interface for read-optimized storage.

    [:material-arrow-right-box: BaseCache](cache.md)

</div>
