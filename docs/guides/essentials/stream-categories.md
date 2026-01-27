# Stream Categories

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

- `ecommerce::order-123` - All messages for Order with ID 123
- `ecommerce::user-456` - All messages for User with ID 456
- `inventory::product-789` - All messages for Product with ID 789

This structure ensures that:

1. All messages for a specific aggregate instance are grouped together
2. Messages can be easily traced to their source aggregate
3. Event sourcing can reconstruct aggregate state from its message stream
4. Messages maintain ordering guarantees within a stream

### Domain-Scoped Categories

Internally, Protean prefixes stream categories with the domain name to create fully qualified stream categories. This ensures uniqueness across different domains in multi-domain applications:

```python
# Your aggregate definition
@domain.aggregate
class Order:
    ...

# Internally becomes: "ecommerce::order"
# Where "ecommerce" is your domain name
```

## Defining Stream Categories

### Aggregates

Stream categories are primarily defined at the aggregate level. By default, the stream category is automatically derived as the snake_case version of the aggregate's class name:

```python
@domain.aggregate
class User:
    ...
# Stream category: "user"

@domain.aggregate
class OrderItem:
    ...
# Stream category: "order_item"
```

You can explicitly specify a stream category:

```python
@domain.aggregate(stream_category="customer_orders")
class Order:
    ...
# Stream category: "customer_orders"
```

Learn more in the [Aggregates configuration](../domain-definition/aggregates.md#stream_category) section.

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

Learn more in the [Events metadata](../domain-definition/events.md#stream-category) section.

### Commands

Commands follow the same pattern as events - they're routed to their target aggregate's stream category:

```python
@domain.command(part_of=Order)
class PlaceOrder:
    order_id = Identifier(required=True)
    # Routes to Order's stream category
```

## Stream Categories in Handlers

Handlers (event handlers, command handlers, and projectors) use stream categories to determine which message streams they subscribe to.

### Default Behavior

Handlers automatically subscribe to their associated aggregate's stream category:

```python
@domain.event_handler(part_of=Order)
class OrderEventHandler:
    # Subscribes to Order's stream category ("order")
    
    @handle(OrderPlaced)
    def handle_order_placed(self, event):
        ...
```

### Explicit Stream Categories

Handlers can explicitly specify which stream category to subscribe to:

```python
@domain.event_handler(part_of=Order, stream_category="all_orders")
class OrderReportHandler:
    # Subscribes to "all_orders" instead of Order's default
    ...
```

This allows multiple aggregates to publish to shared stream categories for specific use cases.

### Cross-Aggregate Subscriptions

A powerful pattern is having handlers that are part of one aggregate but subscribe to another aggregate's stream category. This enables reactive, cross-aggregate coordination:

```python
@domain.event_handler(part_of=Inventory, stream_category="order")
class InventoryEventHandler:
    """Handles order events to update inventory."""
    
    @handle(OrderShipped)
    def reduce_stock(self, event):
        # React to Order events while being part of Inventory
        inventory = self.repository_for(Inventory).get(event.product_id)
        inventory.reduce_stock(event.quantity)
        self.repository_for(Inventory).add(inventory)
```

In this example:

- The handler is part of the `Inventory` aggregate (determines its lifecycle and domain clustering)
- But it subscribes to the `order` stream category (receives Order events)

This pattern is useful for:

- **Maintaining consistency** across aggregate boundaries
- **Building read models** from multiple aggregate streams
- **Coordinating workflows** across different parts of your domain
- **Implementing sagas** that span multiple aggregates

Learn more:

- [Event Handlers](../consume-state/event-handlers.md#configuration-options)
- [Command Handlers](../change-state/command-handlers.md#stream-category)
- [Projections](../consume-state/projections.md#stream-categories)

## Stream Categories in Subscriptions

The Protean [Server/Engine](../server/engine.md) uses stream categories to create subscriptions that poll for new messages and deliver them to handlers.

### Subscription Creation

When the engine starts, it:

1. Identifies all handlers (event handlers, command handlers, projectors)
2. Infers or reads their stream category
3. Creates a subscription for each handler to its stream category
4. Begins polling for messages

```python
# Example: How the engine creates subscriptions
handler_cls = OrderEventHandler
stream_category = "order"  # Inferred from handler

subscription = engine.subscription_factory.create_subscription(
    handler=handler_cls,
    stream_category=stream_category,
)
```

### Multiple Handlers, Same Stream

Multiple handlers can subscribe to the same stream category. Each handler gets its own subscription with independent position tracking:

```python
@domain.event_handler(part_of=Order)
class OrderNotificationHandler:
    # Subscription 1 to "order" stream
    ...

@domain.event_handler(part_of=Order)
class OrderAnalyticsHandler:
    # Subscription 2 to "order" stream
    ...
```

Both handlers receive all events from the `order` stream category, but process them independently at their own pace.

Learn more in [Subscriptions](../server/subscriptions.md#stream-categories).

## Stream Categories and Event Sourcing

For event-sourced aggregates (marked with `is_event_sourced=True`), stream categories become even more critical:

```python
@domain.aggregate(is_event_sourced=True)
class Account:
    account_number = String(required=True)
    balance = Float(default=0.0)
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
@domain.aggregate(fact_events=True)
class User:
    ...

# Regular events: ecommerce::user-123
# Fact events: ecommerce::user-fact-123
```

Fact event streams use the pattern `<stream_category>-fact-<aggregate_id>`, allowing separate subscription management for fact events versus delta events.

Learn more in [Raising Events](../domain-behavior/raising-events.md#fact-events).

## Best Practices

### 1. Use Descriptive Names

Choose stream categories that clearly indicate the aggregate's purpose and align with your domain language:

```python
# Good
@domain.aggregate(stream_category="customer_order")
class Order:
    ...

# Less clear
@domain.aggregate(stream_category="ord")
class Order:
    ...
```

### 2. Be Consistent

Use a consistent naming convention across your domain:

```python
# Consistent: all use snake_case
stream_category="customer_order"
stream_category="order_item"
stream_category="order_shipment"

# Inconsistent: mixed styles
stream_category="customerOrder"
stream_category="order-item"
stream_category="OrderShipment"
```

### 3. Consider Logical Grouping

Related aggregates can share prefixes to indicate their relationship:

```python
@domain.aggregate(stream_category="order")
class Order:
    ...

@domain.aggregate(stream_category="order_item")
class OrderItem:
    ...

@domain.aggregate(stream_category="order_shipment")
class Shipment:
    ...
```

### 4. Override When Necessary

Use explicit stream categories when the default doesn't align with your domain language:

```python
# Default would be "purchase_order" 
@domain.aggregate(stream_category="order")
class PurchaseOrder:
    ...
```

### 5. Document Cross-Subscriptions

When handlers subscribe to other aggregates' streams, document the reason clearly:

```python
@domain.event_handler(part_of=Inventory, stream_category="order")
class InventoryEventHandler:
    """
    Subscribes to order stream to maintain inventory consistency.
    
    When orders are placed or shipped, inventory levels are adjusted
    to reflect the change in available stock.
    """
    ...
```

### 6. Avoid Generic Names

Don't use overly generic stream categories that make it unclear what messages they contain:

```python
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
@domain.aggregate
class Order:
    ...

@domain.event_handler(part_of=Order)
class OrderEventHandler:
    # Subscribes to Order's stream category
    ...
```

### Pattern 2: Single Aggregate, Multiple Handlers

Multiple handlers processing events from the same aggregate:

```python
@domain.aggregate
class Order:
    ...

@domain.event_handler(part_of=Order)
class OrderNotificationHandler:
    ...

@domain.event_handler(part_of=Order)
class OrderAnalyticsHandler:
    ...

@domain.projector(projector_for=OrderSummary, aggregates=[Order])
class OrderSummaryProjector:
    ...
```

Each handler subscribes to the `order` stream category independently.

### Pattern 3: Cross-Aggregate Event Propagation

One aggregate reacting to another's events:

```python
@domain.aggregate
class Order:
    ...

@domain.aggregate
class Inventory:
    ...

@domain.event_handler(part_of=Inventory, stream_category="order")
class InventoryEventHandler:
    """Maintains inventory in response to order events."""
    ...
```

### Pattern 4: Multi-Aggregate Projections

Projections built from multiple aggregate streams:

```python
@domain.projector(
    projector_for=SalesDashboard,
    stream_categories=["order", "customer", "product"]
)
class SalesDashboardProjector:
    """Builds comprehensive sales view from multiple sources."""
    ...
```
