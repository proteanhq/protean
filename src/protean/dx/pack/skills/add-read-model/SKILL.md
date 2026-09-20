---
name: add-read-model
description: Build a complete read model in Protean - a projection populated by a projector that reacts to domain events. Covers single-aggregate projections (flattened view of one aggregate), cross-aggregate projections (combining data from multiple aggregates), and choosing between database-backed and cache-backed storage. Use when the user asks to "add a read model", "create a projection with projector", "build a query view", "add a CQRS read side", "create a denormalized view", "build a reporting view", "add a dashboard query model", or when they need to combine data from multiple aggregates into one queryable structure.
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: workflow
  composes: [projection, projector, event, aggregate]
---

# Add Read Model

A read model is the query side of CQRS. It consists of three parts working together:

1. **Projection** — A denormalized, query-optimized data structure with basic field types only
2. **Projector** — An event listener that populates and updates the projection
3. **Domain events** — The bridge between write-side aggregates and read-side projections

## What this creates

| Component | Purpose | Decorator |
|-----------|---------|-----------|
| Projection | Flat, queryable data structure | `@domain.projection` |
| Projector | Event-to-projection mapper | `@domain.projector(projector_for=..., aggregates=[...])` |
| Events | Carry state changes from aggregates | `@domain.event(part_of=...)` |
| Aggregate factory methods | Raise events on state changes | `raise_()` in aggregate methods |

## Information to gather

Before building a read model, understand:

- [ ] **What query does this serve?** — What data does the UI/API need? (e.g., "product listing with stock levels")
- [ ] **Which aggregates contribute data?** — Single aggregate or multiple? (determines projector configuration)
- [ ] **What events trigger updates?** — Which state changes should update the read model?
- [ ] **What fields are needed?** — Only basic types allowed: String, Integer, Float, Identifier, DateTime, Boolean, Text, Date
- [ ] **What storage is appropriate?** — Database (durable, queryable) or cache (fast, ephemeral)?

## Process

### Step 1: Define the projection

Create a flat data structure with only basic field types. Every projection needs at least one `identifier=True` field.

```python
from protean.fields import DateTime, Float, Identifier, Integer, String

@domain.projection
class ProductListing:
    product_id: Identifier(identifier=True, required=True)
    name: String(max_length=200, required=True)
    price: Float()
    stock_quantity: Integer(default=0)
    category_name: String()        # Flattened from Category aggregate
    last_updated: DateTime()
```

**Key rules for projections** (see [projection](../projection/SKILL.md)):
- Basic field types only — no Reference, HasMany, HasOne, or ValueObject
- At least one field with `identifier=True`
- Flatten nested data into basic fields
- Use `@domain.projection` decorator

### Step 2: Define the events

Events carry the data needed to populate the projection. Define them with `part_of` pointing to their source aggregate.

```python
@domain.event(part_of="Product")
class ProductAdded:
    product_id: Identifier(required=True)
    name: String(required=True)
    price: Float(required=True)
    stock_quantity: Integer(required=True)

@domain.event(part_of="Product")
class ProductPriceChanged:
    product_id: Identifier(required=True)
    new_price: Float(required=True)
```

### Step 3: Raise events from aggregates

Use factory methods or domain methods to raise events when state changes.

```python
@domain.aggregate
class Product:
    name: String(required=True)
    price: Float(required=True)
    stock_quantity: Integer(default=0)

    @classmethod
    def create(cls, name, price, stock_quantity=0):
        product = cls(name=name, price=price, stock_quantity=stock_quantity)
        product.raise_(ProductAdded(
            product_id=product.id,
            name=name,
            price=price,
            stock_quantity=stock_quantity,
        ))
        return product

    def update_price(self, new_price):
        self.price = new_price
        self.raise_(ProductPriceChanged(
            product_id=self.id,
            new_price=new_price,
        ))
```

### Step 4: Build the projector

The projector listens to events and updates the projection. Use `@on` decorator from `protean.core.projector`.

```python
from protean.core.projector import on

@domain.projector(projector_for=ProductListing, aggregates=[Product])
class ProductListingProjector:
    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        repo = domain.repository_for(ProductListing)
        listing = ProductListing(
            product_id=event.product_id,
            name=event.name,
            price=event.price,
            stock_quantity=event.stock_quantity,
        )
        repo.add(listing)

    @on(ProductPriceChanged)
    def on_price_changed(self, event: ProductPriceChanged):
        repo = domain.repository_for(ProductListing)
        listing = repo.get(event.product_id)
        listing.price = event.new_price
        repo.add(listing)
```

### Step 5: Enable synchronous processing (for testing)

```python
domain.config["event_processing"] = "sync"
```

In production, events are processed asynchronously. For testing and development, set `event_processing` to `"sync"` so projectors run immediately when events are raised.

## Single-aggregate vs cross-aggregate

| Aspect | Single-aggregate | Cross-aggregate |
|--------|-----------------|-----------------|
| **Projector config** | `aggregates=[Product]` | `aggregates=[User, Transaction]` |
| **Data source** | One aggregate's events | Multiple aggregates' events |
| **Complexity** | Straightforward mapping | Must handle ordering, missing records |
| **Example** | Product → ProductListing | User + Transaction → UserBalance |

### Cross-aggregate projector

When combining data from multiple aggregates, the projector listens to events from all contributing aggregates:

```python
@domain.projector(
    projector_for=UserBalance,
    aggregates=[User, Transaction],
)
class UserBalanceProjector:
    @on(UserRegistered)
    def on_user_registered(self, event):
        balance = UserBalance(user_id=event.user_id, name=event.name, balance=0.0)
        domain.repository_for(UserBalance).add(balance)

    @on(TransactionCompleted)
    def on_transaction_completed(self, event):
        balance = domain.repository_for(UserBalance).get(event.user_id)
        balance.balance += event.amount
        domain.repository_for(UserBalance).add(balance)
```

## Choosing storage

| Storage | Option | Best for |
|---------|--------|----------|
| **Database** | `@domain.projection` (default) | Durable data, complex queries, reporting |
| **Database (specific)** | `@domain.projection(provider="postgres")` | Explicit provider selection |
| **Cache** | `@domain.projection(cache="redis")` | Fast reads, session data, ephemeral views |

## Decision guide

```
Need a queryable view of domain data?
├── Data from one aggregate only
│   └── Single-aggregate projector
│       aggregates=[TheAggregate]
│
├── Data from multiple aggregates
│   └── Cross-aggregate projector
│       aggregates=[AggregateA, AggregateB]
│
├── Need fast, ephemeral reads?
│   └── Cache-backed projection
│       @domain.projection(cache="redis")
│
└── Need durable, queryable data?
    └── Database-backed projection (default)
        @domain.projection  or  @domain.projection(provider="postgres")
```

## Common mistakes

### Complex field types in a projection

```python
# Wrong! Projections are flat — no associations or value objects
@domain.projection
class ProductListing:
    product_id: Identifier(identifier=True)
    category = Reference(Category)   # No
    reviews = HasMany("Review")      # No
```

Instead: flatten into basic fields (`category_name: String()`, `review_count: Integer()`).

### Business logic in the projector

```python
# Wrong! Projector decides business rules
@on(OrderPlaced)
def on_order_placed(self, event):
    if event.total > 1000:           # rule leaks into the read side
        apply_vip_discount(event)
```

Instead: projectors only map event data into projection rows; keep rules on the write side.

### Handling create but not update

```python
# Wrong! Only the create event is handled — the projection goes stale
@on(ProductAdded)
def on_added(self, event): ...
# (no handler for ProductPriceChanged)
```

Instead: handle every event that changes the projected data, including updates (and deletes).

### Reading the aggregate instead of the projection

```python
# Wrong! The read path queries the write model
orders = domain.repository_for(Order).query.filter(status="placed")
```

Instead: query the projection (`domain.repository_for(ProductListing)` or `view_for`), which is shaped for the query.

### Forgetting sync processing in tests

```python
# Wrong! The projector never runs, so the projection stays empty
domain.process(command)  # async by default
assert domain.repository_for(ProductListing).get("P-1")  # fails
```

Instead: set `domain.config["event_processing"] = "sync"` in tests so projectors run immediately.

## Complete examples

- [Single-aggregate read model](assets/read_model_single_aggregate.py) — Product → ProductListing with create and update events
- [Cross-aggregate read model](assets/read_model_cross_aggregate.py) — User + Order → CustomerOrderSummary combining data from two aggregates
- [Read model with multiple events](assets/read_model_multiple_events.py) — Inventory tracking with stock adjustments, reservations, and releases

## Detailed references

- [Single-Aggregate Read Model](references/single-aggregate-read-model.md) — Step-by-step walkthrough
- [Cross-Aggregate Read Model](references/cross-aggregate-read-model.md) — Combining data from multiple aggregates
- [Choosing Storage](references/choosing-storage.md) — Database vs cache trade-offs

## Related skills

- [projection](../projection/SKILL.md) — Projection definition and field types
- [projector](../projector/SKILL.md) — Projector patterns and configuration
- [event](../event/SKILL.md) — Defining domain events
- [aggregate](../aggregate/SKILL.md) — Aggregates that raise events
