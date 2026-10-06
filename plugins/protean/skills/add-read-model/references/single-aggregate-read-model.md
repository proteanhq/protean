# Single-Aggregate Read Model

A single-aggregate read model provides a query-optimized view of one aggregate's data. This is the simplest and most common read model pattern.

## When to use

- The UI needs a flat, queryable view of aggregate data
- You want to avoid loading the full aggregate for read-only queries
- The projection fields are a subset or transformation of one aggregate's data

## Step-by-step

### 1. Identify the query need

Ask: "What does the consumer (UI, API, report) need to display?" Map those needs to flat fields.

### 2. Define events

Each state change that should update the read model needs an event. Events are named in past tense (`ProductAdded`, `PriceChanged`) and carry the data needed for the projection.

```python
@domain.event(part_of="Product")
class ProductAdded:
    product_id: Identifier(required=True)
    name: String(required=True)
    price: Float(required=True)
```

### 3. Define the projection

Flatten the data into basic field types. The identifier field should match the aggregate's identity.

```python
@domain.projection
class ProductListing:
    product_id: Identifier(identifier=True, required=True)
    name: String(max_length=200, required=True)
    price: Float(required=True)
```

### 4. Raise events from the aggregate

Add factory methods or domain methods that raise events.

```python
@domain.aggregate
class Product:
    name: String(required=True)
    price: Float(required=True)

    @classmethod
    def create(cls, name, price):
        product = cls(name=name, price=price)
        product.raise_(ProductAdded(product_id=product.id, name=name, price=price))
        return product
```

### 5. Build the projector

The projector maps events to projection operations (create, update, delete).

```python
from protean.core.projector import on

@domain.projector(projector_for=ProductListing, aggregates=[Product])
class ProductListingProjector:
    @on(ProductAdded)
    def on_product_added(self, event):
        listing = ProductListing(
            product_id=event.product_id,
            name=event.name,
            price=event.price,
        )
        domain.repository_for(ProductListing).add(listing)
```

### 6. Read the model back

Answer reads with a query and a query handler. The handler reads through `domain.view_for`, which is read-only.

```python
from protean import current_domain, read

@domain.query(part_of=ProductListing)
class GetProductListing:
    product_id: Identifier(required=True)

@domain.query_handler(part_of=ProductListing)
class ProductListingQueryHandler:
    @read(GetProductListing)
    def get_listing(self, query: GetProductListing):
        return current_domain.view_for(ProductListing).get(query.product_id)

domain.config["event_processing"] = "sync"  # run the projector right away
domain.init(traverse=False)

with domain.domain_context():
    product = Product.create(name="Desk Lamp", price=39.0)
    domain.repository_for(Product).add(product)

    listing = domain.dispatch(GetProductListing(product_id=product.id))
    print(listing.name, listing.price)  # Desk Lamp 39.0
```

## Key patterns

- **One projector per projection**: Each projection has its own dedicated projector
- **Event-per-change**: Each distinct state change gets its own event type
- **Projector handles all events for its projection**: One projector can handle multiple events

## Complete example

See [read_model_single_aggregate.py](../assets/read_model_single_aggregate.py) for a complete runnable example with create, price update, and stock update events.
