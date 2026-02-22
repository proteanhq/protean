# Managing Projections

!!! abstract "Applies to: CQRS · Event Sourcing"


Projections, a.k.a Read models, are representations of data optimized for querying
and reading purposes. Projections are designed to provide data in a format that is
easy and efficient to read, often tailored to the specific needs of a
particular view or user interface.

Projections are typically populated in response to Domain Events raised in the
domain model.

## Projections

### Defining a Projection

Projections are defined with the `Domain.projection` decorator.

```python hl_lines="15-19"
--8<-- "guides/consume-state/002.py:67:75"
```

### Projection Configuration Options

Projections in Protean can be configured with several options passed directly to the projection decorator:

```python
@domain.projection(
    provider="postgres",      # Database provider to use
    schema_name="product_inventory",  # Custom schema/table name
    limit=50                  # Default limit for queries
)
class ProductInventory:
    # Projection fields and methods
    pass
```

#### Storage Options

Projections can be stored in either a database or a cache, but not both simultaneously:

- **Database Storage**: Use the `provider` parameter to specify which database provider to use.
  ```python
  @domain.projection(provider="postgres")  # Connect to a PostgreSQL database
  class ProductInventory:
      # Projection fields and methods
      pass
  ```

- **Cache Storage**: Use the `cache` parameter to specify which cache provider to use.
  ```python
  @domain.projection(cache="redis")  # Store projection data in Redis cache
  class ProductInventory:
      # Projection fields and methods
      pass
  ```

When both `cache` and `provider` parameters are specified, the `cache` parameter takes precedence
and the `provider` parameter is ignored.

#### Additional Options

All options are passed directly to the projection decorator:

```python
@domain.projection(
    abstract=False,          # If True, indicates this projection is an abstract base class
    database_model="custom_model",    # Custom model name for storage
    order_by=("name",),      # Default ordering for query results
    schema_name="inventory", # Custom schema/table name
    limit=100                # Default query result limit (set to None for no limit)
)
class ProductInventory:
    # Projection fields and methods
    pass
```

### Querying Projections

Projections are optimized for querying. You can use the repository pattern to query projections:

```python
# Get a single projection record by ID
inventory = repository.get(ProductInventory, id=1)

# Query projection with filters
low_stock_items = repository._dao.filter(
    ProductInventory, 
    quantity__lt=10,
    limit=20
)
```

<!-- FIXME Add note that one can use anything to query projections, and that
repositories are essentially write-side artifacts. -->

---

## Projectors

Projectors are specialized event handlers responsible for maintaining projections by listening to domain events and updating projection data accordingly. They provide the bridge between your domain events and read models, ensuring projections stay synchronized with changes in your domain.

### Defining a Projector

Projectors are defined using the `Domain.projector` decorator and must be associated with a specific projection:

```python hl_lines="15-19"
--8<-- "guides/consume-state/002.py:88:117"
```

### Projector Configuration Options

Projectors can be configured with several options:

```python
@domain.projector(
    projector_for=ProductInventory,     # Required: The projection to maintain
    aggregates=[Product, Order],        # Aggregates to listen to
    stream_categories=["product", "order"]  # Alternative to aggregates
)
class ProductInventoryProjector:
    # Event handler methods
    pass
```

#### Required Configuration

- **`projector_for`**: The projection class that this projector maintains. This parameter is mandatory and establishes the relationship between the projector and its target projection.

#### Event Source Configuration

You must specify either `aggregates` or `stream_categories` (but not both):

- **`aggregates`**: A list of aggregate classes whose events this projector should handle. Protean automatically derives the [stream categories](../essentials/stream-categories.md) from the specified aggregates.

- **`stream_categories`**: A list of [stream category](../essentials/stream-categories.md) names to listen to. This provides more fine-grained control over which event streams the projector monitors.

### Event Handling with `@on`

Projectors use the `@on` decorator (an alias for `@handle`) to specify which events they respond to:

```python hl_lines="15-19"
--8<-- "guides/consume-state/002.py:88:117"
```

### Multiple Event Handlers

A single projector can handle multiple events, and multiple projectors can handle the same event:

```python
@domain.projector(projector_for=OrderSummary, aggregates=[Order])
class OrderSummaryProjector:
    @on(OrderCreated)
    def on_order_created(self, event: OrderCreated):
        # Create order summary
        pass
    
    @on(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        # Update shipping status
        pass
    
    @on(OrderCancelled)
    def on_order_cancelled(self, event: OrderCancelled):
        # Mark as cancelled
        pass

@domain.projector(projector_for=ShippingReport, aggregates=[Order])
class ShippingReportProjector:
    @on(OrderShipped)  # Same event, different projector
    def on_order_shipped(self, event: OrderShipped):
        # Update shipping metrics
        pass
```

### Projector Registration

Projectors can be registered with the domain with the `Domain.projector` decorator:

#### Decorator Registration

```python
@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class ProductInventoryProjector:
    # Event handler methods
    pass
```

### Error Handling in Projectors

Projectors should handle errors gracefully to ensure system resilience:

```python
@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class ProductInventoryProjector:
    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        try:
            repository = domain.repository_for(ProductInventory)
            
            # Check if inventory already exists
            try:
                existing = repository.get(event.product_id)
                # Handle duplicate case
                return
            except NotFoundError:
                pass  # Expected case - create new inventory
            
            inventory = ProductInventory(
                product_id=event.product_id,
                name=event.name,
                price=event.price,
                stock_quantity=event.stock_quantity,
            )
            
            repository.add(inventory)
            
        except Exception as e:
            # Log error and potentially raise for retry mechanisms
            logger.error(f"Failed to process ProductAdded event: {e}")
            raise
```

### Projector Workflow

The projector workflow follows this sequence:

```mermaid
sequenceDiagram
  autonumber
  Aggregate->>Event Store: Publish Event
  Event Store->>Projector: Deliver Event
  Projector->>Projector: Process Event
  Projector->>Repository: Load Projection
  Repository-->>Projector: Return Projection
  Projector->>Projector: Update Projection
  Projector->>Repository: Save Projection
  Repository-->>Projector: Confirm Save
```

1. **Aggregate Publishes Event**: Domain events are published when aggregates change state
2. **Event Store Delivers Event**: The event store routes events to registered projectors
3. **Projector Processes Event**: The projector receives and begins processing the event
4. **Load Projection**: If updating existing data, the projector loads the current projection
5. **Update Projection**: The projector applies changes based on the event data
6. **Save Projection**: The updated projection is persisted to storage

## Projection Update Strategies

There are different strategies for keeping projections up-to-date with your domain model:

1. **Event-driven**: Respond to domain events to update projections (recommended)
2. **Periodic Refresh**: Schedule periodic rebuilding of projections from source data
3. **On-demand Calculation**: Generate projections when they are requested 

The event-driven approach is usually preferred as it ensures projections are updated in near real-time.

## Workflow

`ManageInventory` Command Handler handles `AdjustStock` command, loads the
product and updates it, and then persists the product, generating domain
events.

```mermaid
sequenceDiagram
  autonumber
  App->>Manage Inventory: AdjustStock object
  Manage Inventory->>Manage Inventory: Extract data and load product
  Manage Inventory->>product: adjust stock
  product->>product: Mutate
  product-->>Manage Inventory: 
  Manage Inventory->>Repository: Persist product
  Repository->>Broker: Publish events
```

The events are then consumed by a projector that loads the `inventory` projection
record and updates it.

```mermaid
sequenceDiagram
  autonumber
  Broker-->>Sync Inventory: Pull events
  Sync Inventory->>Sync Inventory: Extract data and load inventory record
  Sync Inventory->>inventory: update
  inventory->>inventory: Mutate
  inventory-->>Sync Inventory: 
  Sync Inventory->>Repository: Persist inventory record
```

## Supported Field Types

Projections can only contain basic field types. References, Associations, and ValueObjects
are not supported in projections. This is because projections are designed to be flattened,
denormalized representations of data.

## Best Practices

When working with projectors, consider these best practices:

### Idempotency

Projectors should be idempotent to handle duplicate events gracefully:

```python
@domain.projector(projector_for=UserProfile, aggregates=[User])
class UserProfileProjector:
    @on(UserRegistered)
    def on_user_registered(self, event: UserRegistered):
        repository = domain.repository_for(UserProfile)
        
        # Check if profile already exists
        try:
            existing_profile = repository.get(event.user_id)
            # Profile already exists, skip creation
            return
        except NotFoundError:
            pass  # Expected case - create new profile
        
        profile = UserProfile(
            user_id=event.user_id,
            email=event.email,
            name=event.name
        )
        repository.add(profile)
```

### Event Ordering

Be aware that events may not always arrive in the expected order. Design projectors to handle out-of-order events:

```python
@domain.projector(projector_for=OrderStatus, aggregates=[Order])
class OrderStatusProjector:
    @on(OrderCreated)
    def on_order_created(self, event: OrderCreated):
        repository = domain.repository_for(OrderStatus)
        
        # Use event timestamp to handle ordering
        status = OrderStatus(
            order_id=event.order_id,
            status="CREATED",
            last_updated=event._metadata.timestamp
        )
        repository.add(status)
    
    @on(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        repository = domain.repository_for(OrderStatus)
        status = repository.get(event.order_id)
        
        # Only update if this event is newer
        if event._metadata.timestamp > status.last_updated:
            status.status = "SHIPPED"
            status.last_updated = event._metadata.timestamp
            repository.add(status)
```

---

## Advanced Usage

### Cross-Aggregate Projections

Projectors can listen to events from multiple aggregates to create comprehensive views:

```python
@domain.projector(
    projector_for=CustomerOrderSummary, 
    aggregates=[Customer, Order, Payment]
)
class CustomerOrderSummaryProjector:
    @on(CustomerRegistered)
    def on_customer_registered(self, event: CustomerRegistered):
        # Initialize customer summary
        pass
    
    @on(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        # Update order count and total
        pass
    
    @on(PaymentProcessed)
    def on_payment_processed(self, event: PaymentProcessed):
        # Update payment status
        pass
```

### Stream Categories

For more granular control, use [stream categories](../essentials/stream-categories.md) instead of aggregates:

```python
@domain.projector(
    projector_for=SystemMetrics,
    stream_categories=["user", "order", "payment", "inventory"]
)
class SystemMetricsProjector:
    @on(UserRegistered)
    def on_user_registered(self, event: UserRegistered):
        # Update user metrics
        pass
    
    @on(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        # Update order metrics
        pass
```

## Complete Example

Below is a comprehensive example showing projections and projectors working together to maintain multiple read models from a single aggregate:

```python hl_lines="79-85 87-93 95-135 137-165"
{! docs_src/guides/consume-state/002.py !}
```

This example demonstrates:

- **Multiple Projections**: `ProductInventory` for detailed inventory tracking and `ProductCatalog` for simplified browsing
- **Multiple Projectors**: Each projection has its own dedicated projector
- **Event Handling**: Both projectors respond to the same events but update different projections
- **Real-time Updates**: Projections are automatically updated when domain events occur
- **Different Data Formats**: Each projection optimizes data for its specific use case

## Testing Projectors

Testing projectors is straightforward since they respond to domain events. Here's how to test them effectively:

### Unit Testing Projector Methods

Test individual projector methods by creating events and calling the methods directly:

```python
import pytest
from protean import Domain

def test_product_inventory_projector_on_product_added():
    domain = Domain()
    # ... register domain elements
    
    with domain.domain_context():
        # Create test event
        event = ProductAdded(
            product_id="test-123",
            name="Test Product",
            description="A test product",
            price=99.99,
            stock_quantity=10
        )
        
        # Create projector instance
        projector = ProductInventoryProjector()
        
        # Call the handler method
        projector.on_product_added(event)
        
        # Verify projection was created
        repository = domain.repository_for(ProductInventory)
        inventory = repository.get("test-123")
        
        assert inventory.name == "Test Product"
        assert inventory.stock_quantity == 10
```

### Integration Testing with Events

Test the complete flow by raising events from aggregates:

```python
def test_projector_integration():
    domain = Domain()
    # ... register domain elements
    
    with domain.domain_context():
        # Create and persist aggregate
        product = Product.create(
            name="Integration Test Product",
            description="Testing projector integration",
            price=149.99,
            stock_quantity=25
        )
        
        product_repo = domain.repository_for(Product)
        product_repo.add(product)  # This triggers events
        
        # Verify projections were updated
        inventory_repo = domain.repository_for(ProductInventory)
        catalog_repo = domain.repository_for(ProductCatalog)
        
        inventory = inventory_repo.get(product.id)
        catalog = catalog_repo.get(product.id)
        
        assert inventory.name == "Integration Test Product"
        assert catalog.in_stock == "YES"
```

### Testing Error Scenarios

Test how projectors handle error conditions:

```python
def test_projector_handles_missing_projection():
    domain = Domain()
    # ... register domain elements
    
    with domain.domain_context():
        event = StockAdjusted(
            product_id="non-existent",
            quantity=-5,
            new_stock_quantity=0
        )
        
        projector = ProductInventoryProjector()
        
        # Should handle missing projection gracefully
        with pytest.raises(NotFoundError):
            projector.on_stock_adjusted(event)
```

---

!!! tip "See also"
    **Concept overviews:**

    - [Projections](../../core-concepts/domain-elements/projections.md) — Read-optimized views in CQRS.
    - [Projectors](../../core-concepts/domain-elements/projectors.md) — Specialized handlers that maintain projections.

    **Patterns:**

    - [Design Events for Consumers](../../patterns/design-events-for-consumers.md) — Structuring events so projectors can build reliable read models.
    - [Idempotent Event Handlers](../../patterns/idempotent-event-handlers.md) — Ensuring projectors handle replayed events correctly.
