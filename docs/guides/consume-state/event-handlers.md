# Event Handlers

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


When an aggregate changes state, other parts of the system often need to
react — updating a different aggregate, sending a notification, or triggering
a downstream process. Putting that logic inside the originating aggregate
would violate its boundary. Event handlers solve this: they listen for
domain events and execute side effects in their own transaction, keeping
aggregates decoupled.

Event handlers consume events raised in an aggregate and help sync the state of
the aggregate with other aggregates and other systems. They are the preferred
mechanism to update multiple aggregates.

## Defining an Event Handler

Event Handlers are defined with the `Domain.event_handler` decorator. Below is
a simplified example of an Event Handler connected to `Inventory` aggregate
syncing stock levels corresponding to changes in the `Order` aggregate.

```python hl_lines="26-27 44"
{! docs_src/guides/consume-state/001.py !}
```

1. `Order` aggregate fires `OrderShipped` event on book being shipped.

2. Event handler picks up the event and updates stock levels in `Inventory`
aggregate.

Simulating a hypothetical example, we can see that the stock levels were
decreased in response to the `OrderShipped` event.

```shell hl_lines="21"
In [1]: order = Order(book_id=1, quantity=10, total_amount=100)

In [2]: domain.repository_for(Order).add(order)
Out[2]: <Order: Order object (id: 62f8fa8d-2963-4539-bd21-860d3bab639e)>

In [3]: inventory = Inventory(book_id=1, in_stock=100)

In [4]: domain.repository_for(Inventory).add(inventory)
Out[4]: <Inventory: Inventory object (id: 9272d70f-b796-417d-8f30-e01302d9f1a9)>

In [5]: order.ship_order()

In [6]: domain.repository_for(Order).add(order)
Out[6]: <Order: Order object (id: 62f8fa8d-2963-4539-bd21-860d3bab639e)>

In [7]: stock = domain.repository_for(Inventory).get(inventory.id)

In [8]: stock.to_dict()
Out[8]: {
 'book_id': '1',
 'in_stock': 90,
 'id': '9272d70f-b796-417d-8f30-e01302d9f1a9'
 }
```

## Event Handler Workflow

Event handlers follow an asynchronous, fire-and-forget pattern. When an event is published, event handlers process it without returning any values to the caller.

```mermaid
sequenceDiagram
  autonumber
  Aggregate->>Domain: Publish Event
  Domain->>Event Store: Store Event
  Event Store-->>Domain: 
  Domain-->>Aggregate: 
  
  Note over Domain,Event Handler: Asynchronous Processing
  
  Event Store->>Event Handler: Deliver Event
  Event Handler->>Event Handler: Process Event
  Event Handler->>Repository: Load/Update Aggregates
  Repository-->>Event Handler: 
  Event Handler->>Event Handler: Perform Side Effects
  Event Handler->>Repository: Persist Aggregates
```

1. **Aggregate Publishes Event**: An action in an aggregate triggers an event to be published.
2. **Domain Stores Event**: The domain stores the event in the event store.
3. **Event Store Confirms Storage**: The event store confirms the event has been stored.
4. **Domain Returns to Aggregate**: The domain returns control to the aggregate.
5. **Event Store Delivers Event**: Asynchronously, the event store delivers the event to all subscribed event handlers.
6. **Event Handler Processes Event**: The event handler receives and processes the event.
7. **Event Handler Loads/Updates Aggregates**: If needed, the event handler loads and updates relevant aggregates.
8. **Repository Returns Data**: The repository returns requested data to the event handler.
9. **Event Handler Performs Side Effects**: The event handler may perform additional side effects (sending emails, updating other systems, etc.).
10. **Event Handler Persists Data and Optionally Raises Events**: The event handler persists the mutated aggregate, which can also raise events.

## Return Values from Event Handlers

Event handlers in Protean follow the standard CQRS pattern where event handlers do not return values to the caller. This deliberate design choice ensures:

1. **Decoupling**: The publisher of events remains completely decoupled from the consumers.
2. **Asynchronous Processing**: Events can be processed in the background without blocking.
3. **Multiple Consumers**: Multiple event handlers can process the same event independently.

If an event handler needs to communicate information as part of its processing, it should:

- Emit new events
- Update relevant aggregates that can be queried later
- Log information for monitoring purposes

## Configuration Options

### Handler Options

- **`part_of`**: The aggregate to which the event handler is connected.
- **`stream_category`**: The event handler listens to events on this [stream
category](../../concepts/async-processing/stream-categories.md). The stream category defaults to the category of the aggregate associated with the handler.

    An Event Handler can be part of an aggregate, and have the stream category of
    a different aggregate. This is the mechanism for an aggregate to listen to
    another aggregate's events to sync its own state. Learn more in the
    [Stream Categories](../../concepts/async-processing/stream-categories.md) guide.

- **`source_stream`**: When specified, the event handler only consumes events
generated in response to events or commands from this original stream.
For example, `EmailNotifications` event handler listening to `OrderShipped`
events can be configured to generate a `NotificationSent` event only when the
`OrderShipped` event (in stream `orders`) is generated in response to a
`ShipOrder` (in stream `manage_order`) command.

### Subscription Options

Event handlers can be configured with subscription options that control how
messages are consumed when running the [Protean server](../../concepts/async-processing/index.md):

- **`subscription_type`**: Type of subscription to use:
    - `"stream"`: Uses Redis Streams with consumer groups (recommended for
      production)
    - `"event_store"`: Reads directly from event store (for projections/replay)

- **`subscription_profile`**: Pre-configured profile for common scenarios:
    - `"production"`: High throughput with reliability guarantees
    - `"fast"`: Low-latency processing
    - `"batch"`: High-volume batch processing
    - `"debug"`: Development and debugging
    - `"projection"`: Building read models (uses event_store type)

- **`subscription_config`**: Dictionary of specific configuration options:
    - `messages_per_tick`: Messages to process per batch
    - `blocking_timeout_ms`: Timeout for blocking reads (stream only)
    - `max_retries`: Retry attempts before DLQ (stream only)
    - `enable_dlq`: Enable dead letter queue (stream only)
    - `position_update_interval`: Position update frequency (event_store only)

#### Example with Subscription Configuration

```python
@domain.event_handler(
    part_of=Order,
    subscription_profile="production",
    subscription_config={
        "messages_per_tick": 100,
        "enable_dlq": True,
    }
)
class OrderEventHandler:
    @handle(OrderCreated)
    def send_confirmation(self, event):
        ...
```

See [Server → Configuration](../../reference/server/configuration.md) for detailed
configuration options and the priority hierarchy.

## Error Handling

Protean provides a robust error handling mechanism for event handlers through the optional `handle_error` method. This method allows event handlers to gracefully recover from exceptions without disrupting the overall event processing pipeline.

### The `handle_error` Method

You can add a `handle_error` class method to your event handler to implement custom error handling:

```python
@domain.event_handler(part_of=Inventory)
class InventoryEventHandler:
    @handle(OrderShipped)
    def update_inventory(self, event):
        # Event handling logic that might raise exceptions
        ...
    
    @classmethod
    def handle_error(cls, exc: Exception, message):
        """Custom error handling for event processing failures"""
        # Log the error
        logger.error(f"Failed to process event {message.type}: {exc}")
        
        # Perform recovery operations
        # Example: store failed events for retry, trigger compensating actions, etc.
        ...
```

### How It Works

1. When an exception occurs during event processing, the Protean Engine catches it.
2. The engine logs detailed error information including stack traces.
3. The engine calls the event handler's `handle_error` method, passing:
   - The original exception that was raised
   - The event message being processed when the exception occurred
4. After `handle_error` completes, processing continues with subsequent events.

### Error Handler Failures

If an exception occurs within the `handle_error` method itself, the Protean Engine will catch and log that exception as well, ensuring that the event processing pipeline continues to function. This provides an additional layer of resilience:

```python
@classmethod
def handle_error(cls, exc: Exception, message):
    try:
        # Error handling logic that might itself fail
        ...
    except Exception as error_exc:
        # The engine will catch and log this secondary exception
        logger.error(f"Error handler failed: {error_exc}")
        # Processing continues regardless
```

---

!!! tip "See also"
    **Concept overview:** [Event Handlers](../../concepts/building-blocks/event-handlers.md) — How event handlers consume and react to domain events.

    **Patterns:**

    - [Idempotent Event Handlers](../../patterns/idempotent-event-handlers.md) — Ensuring handlers produce correct results even with duplicate delivery.
    - [Thin Handlers, Rich Domain](../../patterns/thin-handlers-rich-domain.md) — Keeping handlers thin by delegating to domain logic.
