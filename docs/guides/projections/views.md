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
--8<-- "guides/projections/001.py:60:66"
```

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

The events are then consumend by the event handler that loads the view record
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

## Example

Below is a full-blown example of a view `ProductInventory` synced with the
`Product` aggregate with the help of `ProductAdded` and `StockAdjusted` domain
events.

```python hl_lines="68-74 115-127 129-136"
{! docs_src/guides/projections/001.py !}
```
