# Stream Categories

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


Stream categories are a fundamental concept in Protean that organize and route messages (events and commands) throughout your application. They provide the foundation for message subscriptions, event sourcing, and cross-aggregate coordination.

## What is a Stream Category?

A stream category is a logical name that groups related messages together. When an aggregate raises events or processes commands, these messages are organized by their stream category, enabling handlers to subscribe to specific message streams.

Think of stream categories as "channels" or "topics" through which aggregates communicate with the rest of your system. All events raised by an aggregate and all commands targeting it are organized under its stream category.

## How Stream Categories Work

### Message Organization

Messages in Protean are organized in streams with a hierarchical naming structure:

```text
<domain>::<stream_category>-<aggregate_id>
```

For example:

- `ecommerce::order-123`: All messages for Order with ID 123
- `ecommerce::user-456`: All messages for User with ID 456
- `inventory::product-789`: All messages for Product with ID 789

This structure ensures that:

1. All messages for a specific aggregate instance are grouped together
2. Messages can be easily traced to their source aggregate
3. Event sourcing can reconstruct aggregate state from its message stream
4. Messages maintain ordering guarantees within a stream

### Domain-Scoped Categories

Internally, Protean prefixes stream categories with the domain name to create fully qualified stream categories. This ensures uniqueness across different domains in multi-domain applications:

```python
--8<-- "concepts/async-processing/stream-categories/001.py:order"
```

## Defining Stream Categories

### Aggregates

Stream categories are primarily defined at the aggregate level. By default, the stream category is automatically derived as the snake_case version of the aggregate's class name:

```python
--8<-- "concepts/async-processing/stream-categories/001.py:default_names"
```

You can explicitly specify a stream category:

```python
--8<-- "concepts/async-processing/stream-categories/002.py:explicit"
```

Learn more in the [Aggregates configuration](../../guides/domain-definition/aggregates.md#stream_category) section.

### Events

Events inherit their stream category from their associated aggregate. The event's metadata includes a `stream` field that contains the full stream name:

```json
{
    "stream": "ecommerce::order-123",
    "type": "ecommerce.OrderPlaced.v1",
    ...
}
```

This stream name is automatically constructed from the aggregate's stream category and identity.

Learn more in the [Events metadata](../../guides/domain-definition/events.md#stream-category) section.

### Commands

Commands are routed by their target aggregate's stream category too. They go to a
separate command stream, `<stream_category>:command`, so a command for `Order` is
stored in `ecommerce::order:command-<id>`:

```python
--8<-- "concepts/async-processing/stream-categories/001.py:command"
```

## Stream Categories in Handlers

Handlers (event handlers, command handlers, and projectors) use stream categories to determine which message streams they subscribe to.
Event handlers and projectors read the aggregate's stream category. Command
handlers read its command stream, `<stream_category>:command`, as shown above.

### Default Behavior

An event handler subscribes to its aggregate's stream category by default:

```python
--8<-- "concepts/async-processing/stream-categories/003.py:default_handler"
```

### Explicit Stream Categories

Handlers can explicitly specify which stream category to subscribe to:

```python
--8<-- "concepts/async-processing/stream-categories/003.py:explicit_handler"
```

This allows multiple aggregates to publish to shared stream categories for specific use cases.
A handler like this one reads every event on the shared stream with `@handle("$any")`,
for a report or an audit log, and leaves every aggregate as it is.

### Changing Another Aggregate

When an event on one aggregate's stream must change another aggregate, the
handler stays with the aggregate that owns the event. It issues a command, and
the other aggregate's command handler does the write. Take an `Order` that
raises `OrderShipped`, and an `Inventory` that changes through a `ReduceStock`
command:

```python
--8<-- "concepts/async-processing/stream-categories/004.py:model"
```

The event handler on `Order` issues the command, and Inventory's command handler
applies it:

```python
--8<-- "concepts/async-processing/stream-categories/004.py:hand_off"
```

In this example:

- The event handler is part of `Order` and reads the `order` stream category,
  where `OrderShipped` is raised.
- `ReduceStock` is part of `Inventory`, so it is routed to Inventory's command
  handler. `Inventory` changes only through that handler.

Do not make an event handler part of one aggregate and have it handle another
aggregate's events so it can change its own aggregate from there. `protean
check` reports `EVENT_HANDLER_FOREIGN_EVENT` when a handler handles an event
that a single other aggregate in the same domain defines. The
[event handlers guide](../../guides/consume-state/event-handlers.md#defining-an-event-handler)
has a full, runnable version of this hand-off.

Learn more:

- [Event Handlers](../../guides/consume-state/event-handlers.md#configuration-options)
- [Command Handlers](../../guides/change-state/command-handlers.md#stream-category)
- [Projections](../../guides/consume-state/projections.md)

## Stream Categories in Subscriptions

The Protean [Server/Engine](./engine.md) uses stream categories to create subscriptions that poll for new messages and deliver them to handlers.

### Subscription Creation

When the engine starts, it:

1. Identifies all handlers (event handlers, command handlers, projectors)
2. Infers or reads their stream category
3. Creates a subscription for each event handler and projector on its stream
   category, and one subscription per command stream category, which hands
   each command to the handler registered for it
4. Begins polling for messages

```python
# fragment
# Example: How the engine creates subscriptions
handler_cls = OrderEventHandler
stream_category = "ecommerce::order"  # Inferred from handler

subscription = engine.subscription_factory.create_subscription(
    handler=handler_cls,
    stream_category=stream_category,
)
```

### Multiple Handlers, Same Stream

Multiple handlers can subscribe to the same stream category. Each handler gets its own subscription with independent position tracking:

```python
--8<-- "concepts/async-processing/stream-categories/005.py:same_stream"
```

Both handlers receive all events from the `order` stream category, but process them independently at their own pace.

Learn more in [Subscriptions](./subscriptions.md#stream-categories).

## Stream Categories and Event Sourcing

For event-sourced aggregates (marked with `event_sourced=True`), stream categories become even more critical:

```python
--8<-- "concepts/async-processing/stream-categories/006.py:event_sourced"
```

In event-sourced aggregates:

1. **All state changes** are captured as events in the aggregate's stream
2. **Aggregate state** is reconstructed by replaying events from its stream
3. **No traditional database** is needed to store aggregate state
4. **Complete audit trail** is maintained in the event stream

The stream for an event-sourced aggregate instance (e.g., `ecommerce::account-123`) contains the complete history of that aggregate's state changes.

## Fact Events and Stream Categories

When aggregates are configured with `fact_events=True`, Protean generates special fact events that use a modified stream category:

```python
--8<-- "concepts/async-processing/stream-categories/006.py:fact_events"
```

Fact event streams use the pattern `<stream_category>-fact-<aggregate_id>`, allowing separate subscription management for fact events versus delta events.

Learn more in [Raising Events](../../guides/domain-behavior/raising-events.md#fact-events).

## Best Practices

### 1. Use Descriptive Names

Choose stream categories that clearly indicate the aggregate's purpose and align with your domain language:

```python
--8<-- "concepts/async-processing/stream-categories/007.py:descriptive"
--8<-- "concepts/async-processing/stream-categories/007.py:less_clear"
```

### 2. Be Consistent

Use a consistent naming convention across your domain:

```python
--8<-- "concepts/async-processing/stream-categories/008.py:consistent"
```

### 3. Consider Logical Grouping

Related aggregates can share prefixes to indicate their relationship:

```python
--8<-- "concepts/async-processing/stream-categories/008.py:grouping"
```

### 4. Override When Necessary

Use explicit stream categories when the default doesn't align with your domain language:

```python
--8<-- "concepts/async-processing/stream-categories/008.py:override"
```

### 5. Change Another Aggregate Through a Command

By default, a handler subscribes to the stream of the aggregate it is part of. When an
event must change a different aggregate, the handler issues a command to that
aggregate, as shown in [Changing Another Aggregate](#changing-another-aggregate).
Each aggregate then changes only through its own command handler.

### 6. Avoid Generic Names

Don't use overly generic stream categories that make it unclear what messages they contain:

```python
# fragment
# Avoid
@domain.aggregate(stream_category="data")
@domain.aggregate(stream_category="entity")
@domain.aggregate(stream_category="items")

# Better
@domain.aggregate(stream_category="product")
@domain.aggregate(stream_category="customer")
@domain.aggregate(stream_category="order")
```

## Common Patterns

### Pattern 1: Single Aggregate, Single Handler

The simplest pattern - one aggregate, one handler:

```python
--8<-- "concepts/async-processing/stream-categories/009.py:single_handler"
```

### Pattern 2: Single Aggregate, Multiple Handlers

Multiple handlers processing events from the same aggregate:

```python
--8<-- "concepts/async-processing/stream-categories/010.py:multiple_handlers"
```

Each handler subscribes to the `order` stream category independently.

### Pattern 3: Cross-Aggregate Event Propagation

One aggregate reacting to another's events. The event handler stays with
`Order` and issues a command that `Inventory` handles:

```python
--8<-- "concepts/async-processing/stream-categories/011.py:cross_aggregate"
```

### Pattern 4: Multi-Aggregate Projections

Projections built from multiple aggregate streams:

```python
--8<-- "concepts/async-processing/stream-categories/012.py:multi_aggregate"
```
