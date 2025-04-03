# Views

Views, a.k.a Read models, are representations of data optimized for querying
and reading purposes. It is designed to provide data in a format that makes it
easy and efficient to read, often tailored to the specific needs of a
particular view or user interface.

Views are typically populated in response to Domain Events raised in the
domain model.

## Defining a View

Views are defined with the `Domain.view` decorator.

```python hl_lines="15-19"
--8<-- "guides/consume-state/002.py:68:74"
```

## View Configuration Options

Views in Protean can be configured with several options passed directly to the view decorator:

```python
@domain.view(
    provider="postgres",      # Database provider to use
    schema_name="product_inventory",  # Custom schema/table name
    limit=50                  # Default limit for queries
)
class ProductInventory:
    # View fields and methods
    pass
```

### Storage Options

Views can be stored in either a database or a cache, but not both simultaneously:

- **Database Storage**: Use the `provider` parameter to specify which database provider to use.
  ```python
  @domain.view(provider="postgres")  # Connect to a PostgreSQL database
  class ProductInventory:
      # View fields and methods
      pass
  ```

- **Cache Storage**: Use the `cache` parameter to specify which cache provider to use.
  ```python
  @domain.view(cache="redis")  # Store view data in Redis cache
  class ProductInventory:
      # View fields and methods
      pass
  ```

When both `cache` and `provider` parameters are specified, the `cache` parameter takes precedence
and the `provider` parameter is ignored.

### Additional Options

All options are passed directly to the view decorator:

```python
@domain.view(
    abstract=False,          # If True, indicates this view is an abstract base class
    model="custom_model",    # Custom model name for storage
    order_by=("name",),      # Default ordering for query results
    schema_name="inventory", # Custom schema/table name
    limit=100                # Default query result limit (set to None for no limit)
)
class ProductInventory:
    # View fields and methods
    pass
```

## Querying Views

Views are optimized for querying. You can use the repository pattern to query views:

```python
# Get a single view record by ID
inventory = repository.get(ProductInventory, id=1)

# Query view with filters
low_stock_items = repository._dao.filter(
    ProductInventory, 
    quantity__lt=10,
    limit=20
)
```

## View Projection Strategies

There are different strategies for keeping views up-to-date with your domain model:

1. **Event-driven**: Respond to domain events to update views (recommended)
2. **Periodic Refresh**: Schedule periodic rebuilding of views from source data
3. **On-demand Calculation**: Generate views when they are requested 

The event-driven approach is usually preferred as it ensures views are updated in near real-time.

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

The events are then consumed by the event handler that loads the view record
and updates it.

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

Views can only contain basic field types. References, Associations, and ValueObjects 
are not supported in views. This is because views are designed to be flattened, 
denormalized representations of data.

## Example

Below is a full-blown example of a view `ProductInventory` synced with the
`Product` aggregate with the help of `ProductAdded` and `StockAdjusted` domain
events.

```python hl_lines="68-74 115-127 129-136"
{! docs_src/guides/consume-state/001.py !}
```
