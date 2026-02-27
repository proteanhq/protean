# Design Projection Granularity Around Consumer Needs

## The Problem

Developers new to CQRS face a fundamental design question: how many projections
should I create, and what should each one contain? The answer usually falls into
one of two extremes, both of which cause problems.

### Extreme 1: Mirror the aggregate

The most common first instinct is to create one projection per aggregate that
mirrors its structure:

```python
# Anti-pattern: projection that mirrors the Order aggregate 1:1
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    customer_name: String(required=True)
    items = HasMany(OrderItem)
    status: String(default="draft")
    total: Float(default=0.0)
    placed_at: DateTime()
    shipped_at: DateTime()


@domain.projection
class OrderProjection:
    order_id: Identifier(identifier=True)
    customer_id: Identifier()
    customer_name: String()
    status: String()
    total: Float()
    placed_at: DateTime()
    shipped_at: DateTime()
    # Where are the items? Need a separate projection for those,
    # plus a join to combine them. Same complexity as the write side.
```

This defeats the purpose of CQRS. The read model mirrors the write model, so
you get the same joins and complexity. The projection adds maintenance burden
without any benefit.

The symptoms:

- **API handlers still need joins.** The order list endpoint needs customer
  names, so it joins the order projection with a customer projection -- the same
  join the write side would have needed.

- **Projectors are trivial copy machines.** Every projector just copies fields
  from the event to the projection. No transformation, no denormalization, no
  value added.

- **No read-side optimization.** Queries against the projection are no faster
  than queries against the aggregate's table, because the data shape is
  identical.

### Extreme 2: One projection per endpoint

The opposite instinct is to create a perfectly denormalized projection for
every API endpoint or UI component:

```python
# Anti-pattern: hyper-specific projections for every endpoint
@domain.projection
class OrderListItem:       # For GET /orders
    order_id: Identifier(identifier=True)
    customer_name: String()
    status: String()
    total: Float()

@domain.projection
class OrderDetail:         # For GET /orders/{id}
    order_id: Identifier(identifier=True)
    customer_name: String()
    customer_email: String()
    status: String()
    total: Float()
    item_count: Integer()
    shipped_at: DateTime()

@domain.projection
class OrderForShipping:    # For the shipping dashboard
    order_id: Identifier(identifier=True)
    customer_name: String()
    status: String()
    tracking_number: String()

# ... and a projector for each one, all listening to the same events
```

Now you have three projections and three projectors all maintaining overlapping
data from the same events. The consequences:

- **Maintenance explosion.** Every new event field must be propagated to every
  projection that needs it. Adding a `discount_amount` to `OrderPlaced` means
  updating four projectors.

- **Rebuild cost.** Rebuilding projections means replaying events through all
  four projectors. With millions of orders, this takes four times as long.

- **Staleness windows.** Each projection updates independently. During high
  load, the list view might show "shipped" while the detail view still shows
  "placed" because its projector is lagging.

- **Schema proliferation.** The database accumulates tables that are 80%
  identical, wasting storage and complicating migrations.

The root cause of both extremes: **projections were designed around domain
entities (one per aggregate) or infrastructure concerns (one per endpoint),
rather than around what consumers actually need**.

---

## The Pattern

Design each projection around a **consumer need** -- a UI view, an API resource,
or a query pattern -- not around a domain entity or an endpoint.

```
Wrong mental model:
  "I have an Order aggregate, so I need an Order projection."

Also wrong:
  "I have five endpoints that show orders, so I need five projections."

Right mental model:
  "What distinct read patterns do my consumers have? Each pattern
   gets one projection, shaped to serve it directly."
```

### The decision framework

For every screen, API resource, or query pattern, ask these questions:

1. **What data does the consumer need?** List the fields. If they span multiple
   aggregates, the projection should combine them -- that is the whole point of
   a read model.

2. **How is the data accessed?** By primary key lookup? By filtered search with
   sorting? By key-value cache hit? This determines whether the projection is
   database-backed (needs queries) or cache-backed (needs fast key lookups).

3. **How volatile is the data?** If it changes every few seconds (dashboard
   counters, live status), consider a cache-backed projection. If it changes
   infrequently but needs complex queries (order history with filters), use
   database-backed.

4. **Does another projection already serve 80% of this need?** If two consumers
   need almost the same data, prefer one projection with a few optional fields
   over two separate projections. The API layer can select which fields to
   return.

### Rules of thumb

| Situation | Guidance |
|-----------|----------|
| Two views need the same data | One projection, two API endpoints |
| Two views share 80% of fields | One projection with optional fields |
| Two views need fundamentally different data | Two projections |
| Data is queried by filters and sorting | Database-backed (`provider="default"`) |
| Data is looked up by ID for fast display | Cache-backed (`cache="default"`) |
| Data spans multiple aggregates | One cross-aggregate projection with multi-aggregate projector |
| Data mirrors the aggregate exactly | You probably don't need a projection at all |

---

## Applying the Pattern

### Example 1: Cross-aggregate projection

An order summary page needs data from three aggregates: Order (status, total),
Customer (name, email), and Product (item names). Instead of three projections
with joins, build one denormalized projection:

```python
@domain.projection
class OrderSummary:
    """Serves the order list page and the order detail page.

    Combines data from Order, Customer, and Product aggregates
    into a single denormalized read model.
    """
    order_id: Identifier(identifier=True)
    customer_id: Identifier()
    customer_name: String()
    customer_email: String()
    status: String()
    total: Float()
    item_count: Integer()
    placed_at: DateTime()
    shipped_at: DateTime()
    tracking_number: String()
```

The projector listens to events from multiple aggregates using
`stream_categories`:

```python
from protean.core.projector import on


@domain.projector(
    projector_for=OrderSummary,
    stream_categories=["order", "customer"],
)
class OrderSummaryProjector:

    @on(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced) -> None:
        repo = current_domain.repository_for(OrderSummary)
        repo.add(OrderSummary(
            order_id=event.order_id,
            customer_id=event.customer_id,
            customer_name=event.customer_name,
            customer_email=event.customer_email,
            status="placed",
            total=event.total,
            item_count=len(event.items),
            placed_at=event.placed_at,
        ))

    @on(OrderShipped)
    def on_order_shipped(self, event: OrderShipped) -> None:
        repo = current_domain.repository_for(OrderSummary)
        summary = repo.get(event.order_id)
        summary.status = "shipped"
        summary.shipped_at = event.shipped_at
        summary.tracking_number = event.tracking_number
        repo.add(summary)

    @on(CustomerNameChanged)
    def on_customer_name_changed(self, event: CustomerNameChanged) -> None:
        """Update all orders for this customer when their name changes."""
        view = current_domain.view_for(OrderSummary)
        results = view.query.filter(customer_id=event.customer_id).all()
        repo = current_domain.repository_for(OrderSummary)
        for order in results.items:
            order.customer_name = event.new_name
            repo.add(order)
```

!!! note "Cross-aggregate ordering"
    When a projector listens to multiple stream categories, `rebuild_projection()`
    merges events by `global_position` so that cross-aggregate events are replayed
    in the correct chronological order. This is critical for projections where
    event ordering across aggregates matters.

The key insight: the `OrderSummary` projection does not mirror any single
aggregate. It combines data from Order and Customer into the shape that the
consumer (the order list/detail page) needs. The projector handles events from
both aggregates, keeping the projection current as either side changes.

---

### Example 2: Cache-backed projection for a real-time dashboard

A warehouse dashboard shows live order counts by status. The data changes
every few seconds as orders move through the pipeline. A database-backed
projection would add unnecessary I/O for data that is only ever looked up
by a single key:

```python
@domain.projection(cache="default")
class WarehouseDashboard:
    """Real-time order status counts for the warehouse display.

    Cache-backed because:
    - Looked up by a single key (warehouse_id)
    - Updates frequently (every order status change)
    - Never queried with filters or sorting
    - Acceptable to lose on cache eviction (rebuilt from events)
    """
    warehouse_id: Identifier(identifier=True)
    pending_count: Integer(default=0)
    processing_count: Integer(default=0)
    shipped_count: Integer(default=0)
    delivered_count: Integer(default=0)
    last_updated: DateTime()
```

```python
from datetime import datetime, timezone


@domain.projector(
    projector_for=WarehouseDashboard,
    aggregates=[Order],
)
class WarehouseDashboardProjector:

    @on(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced) -> None:
        repo = current_domain.repository_for(WarehouseDashboard)
        try:
            dashboard = repo.get(event.warehouse_id)
        except ObjectNotFoundError:
            dashboard = WarehouseDashboard(
                warehouse_id=event.warehouse_id,
            )
        dashboard.pending_count += 1
        dashboard.last_updated = datetime.now(timezone.utc)
        repo.add(dashboard)

    @on(OrderShipped)
    def on_order_shipped(self, event: OrderShipped) -> None:
        repo = current_domain.repository_for(WarehouseDashboard)
        dashboard = repo.get(event.warehouse_id)
        dashboard.processing_count -= 1
        dashboard.shipped_count += 1
        dashboard.last_updated = datetime.now(timezone.utc)
        repo.add(dashboard)

    @on(OrderDelivered)
    def on_order_delivered(self, event: OrderDelivered) -> None:
        repo = current_domain.repository_for(WarehouseDashboard)
        dashboard = repo.get(event.warehouse_id)
        dashboard.shipped_count -= 1
        dashboard.delivered_count += 1
        dashboard.last_updated = datetime.now(timezone.utc)
        repo.add(dashboard)
```

The API layer reads from the cache via `ReadView`:

```python
view = domain.view_for(WarehouseDashboard)
dashboard = view.get("warehouse-east-1")
```

!!! warning "Cache-backed limitations"
    Cache-backed projections only support `get()`, `count()`, and `exists()` on
    the `ReadView`. They do not support `query` or `find_by()` because cache
    stores are key-value backends. If you need filtered queries, use a
    database-backed projection.

---

### Example 3: Database-backed projection for searchable order history

A customer service tool needs to search orders by date range, status, and
customer name. This requires a database-backed projection:

```python
@domain.projection(provider="default")
class OrderHistory:
    """Searchable order history for customer service.

    Database-backed because it needs filtering, ordering, and pagination.
    """
    order_id: Identifier(identifier=True)
    customer_id: Identifier()
    customer_name: String()
    status: String()
    total: Float()
    placed_at: DateTime()
    shipped_at: DateTime()
    cancelled_at: DateTime()
    cancellation_reason: String()
```

The projector follows the same pattern as Example 1 -- listening to `order` and
`customer` stream categories, handling each event type to create or update the
projection. The key difference is in how consumers query it:

```python
view = domain.view_for(OrderHistory)

# Find all orders for a customer, newest first
orders = view.query.filter(customer_id="cust-123").order_by("-placed_at").all()

# Find cancelled orders in a date range
cancelled = (
    view.query
    .filter(status="cancelled")
    .filter(cancelled_at__gte=start_date)
    .filter(cancelled_at__lte=end_date)
    .all()
)

# Count pending orders
pending_count = view.query.filter(status="placed").all().total
```

Database-backed projections give you the full `ReadView` query API: `filter()`,
`order_by()`, `limit()`, `count()`, and `exists()`. This is what makes them the
right choice when the consumer needs to search, sort, or paginate.

---

### Example 4: Shared projection serving two similar API endpoints

The order list page and the order detail page need almost the same data. The
detail page just needs a few extra fields (tracking number, cancellation reason).
Instead of two projections, use one with optional fields:

```python
@domain.projection
class OrderView:
    """Serves both the order list and order detail endpoints.

    The list endpoint returns: order_id, customer_name, status, total, placed_at
    The detail endpoint returns: all fields

    One projection, two serializers in the API layer.
    """
    order_id: Identifier(identifier=True)
    customer_id: Identifier()
    customer_name: String()
    customer_email: String()
    status: String()
    total: Float()
    item_count: Integer()
    placed_at: DateTime()
    # Detail-only fields (optional, populated when available)
    shipped_at: DateTime()
    delivered_at: DateTime()
    tracking_number: String()
    cancellation_reason: String()
```

The API layer selects which fields to expose:

```python
# In your FastAPI or equivalent API layer

def get_orders():
    """GET /orders -- list view, subset of fields."""
    view = domain.view_for(OrderView)
    orders = view.query.order_by("-placed_at").limit(50).all()
    return [
        {
            "order_id": o.order_id,
            "customer_name": o.customer_name,
            "status": o.status,
            "total": o.total,
            "placed_at": o.placed_at,
        }
        for o in orders
    ]


def get_order(order_id: str):
    """GET /orders/{id} -- detail view, all fields."""
    view = domain.view_for(OrderView)
    order = view.get(order_id)
    return order.to_dict()
```

This approach works because:

- **One projector** maintains one projection. Adding a field means updating one
  projector, not two.
- **One rebuild** replays events once, not twice.
- **Consistent staleness.** Both views are always at the same version of the
  data.
- **The API layer owns field selection**, which is its responsibility anyway.
  The projection owns the data shape; the API owns the response shape.

!!! tip "The 80% rule"
    When two consumers share 80% or more of their fields, prefer one projection
    with optional fields. When they share less than 50%, they probably represent
    genuinely different read patterns and deserve separate projections. The 50-80%
    range is a judgment call -- lean toward fewer projections unless the optional
    fields are expensive to maintain.

---

### Example 5: Knowing when NOT to use a projection

Sometimes the right answer is to not create a projection at all. If the read
pattern matches the aggregate structure exactly and the data lives in one
aggregate, query the aggregate's repository directly:

```python
# No projection needed -- the aggregate is the read model
@domain.aggregate
class Product:
    product_id: Auto(identifier=True)
    name: String(required=True)
    description: Text()
    price: Float(required=True)
    category: String()
    is_active: Boolean(default=True)


# The product detail page needs exactly these fields.
# No cross-aggregate data, no denormalization needed.
# Query the aggregate repository directly.
repo = domain.repository_for(Product)
product = repo.get(product_id)
```

Create a projection only when the read model's shape differs from the write
model -- because it combines multiple aggregates, precomputes derived data,
or optimizes for a specific query pattern that the aggregate's table does
not support well.

---

## Anti-Patterns

### The carbon copy projection

```python
# Anti-pattern: projection is a field-for-field copy of the aggregate
@domain.aggregate
class Invoice:
    invoice_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    amount: Float(required=True)
    status: String(default="draft")
    issued_at: DateTime()
    due_at: DateTime()

@domain.projection
class InvoiceProjection:
    invoice_id: Identifier(identifier=True)
    customer_id: Identifier()
    amount: Float()
    status: String()
    issued_at: DateTime()
    due_at: DateTime()
    # Identical structure. What's the point?
```

If the projection mirrors the aggregate, you are maintaining two copies of the
same data with no benefit. Either add consumer-specific value (join in customer
name, precompute derived fields) or remove the projection entirely.

### The per-endpoint explosion

```python
# Anti-pattern: separate projections for every slight variation
@domain.projection
class InvoiceListView:       # list page
    invoice_id: Identifier(identifier=True)
    customer_name: String()
    amount: Float()
    status: String()

@domain.projection
class InvoiceDetailView:     # detail page
    invoice_id: Identifier(identifier=True)
    customer_name: String()
    customer_email: String()
    amount: Float()
    status: String()
    issued_at: DateTime()

@domain.projection
class InvoiceForExport:      # CSV export
    invoice_id: Identifier(identifier=True)
    customer_name: String()
    amount: Float()
    issued_at: DateTime()

# Three projections, three projectors, all overlapping.
```

These share most of their fields. Consolidate into one `InvoiceView` with
optional fields and let the API layer select what to return.

### The projector that queries aggregates

```python
# Anti-pattern: projector loads aggregates to fill projection fields
@domain.projector(projector_for=OrderSummary, aggregates=[Order])
class OrderSummaryProjector:

    @on(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced) -> None:
        # Event only has order_id -- must load the aggregate
        order = current_domain.repository_for(Order).get(event.order_id)
        customer = current_domain.repository_for(Customer).get(order.customer_id)

        repo = current_domain.repository_for(OrderSummary)
        repo.add(OrderSummary(
            order_id=order.order_id,
            customer_name=customer.name,  # Loaded from Customer aggregate
            total=order.total,
        ))
```

If the projector loads aggregates to get data, the events are too thin. Fix the
events first -- they should carry enough context for the projector to work
independently. See [Design Events for Consumers](design-events-for-consumers.md).

### The orphaned projection

A projection that no API endpoint or UI view actually reads. This happens when
endpoints are deleted or refactored but the projection and projector remain.
The projector keeps processing events, writing data that nobody reads. Audit
your projections periodically: if nothing calls `view_for()` or
`repository_for()` on a projection, remove it.

---

## Summary

| Aspect | Mirror-the-Aggregate | Per-Endpoint | Consumer-Oriented (Pattern) |
|--------|---------------------|--------------|----------------------------|
| Number of projections | One per aggregate | One per endpoint | One per distinct read pattern |
| Data shape | Same as write model | Hyper-specific | Shaped for consumer need |
| Cross-aggregate data | Requires joins | Fully denormalized | Denormalized where needed |
| Projector count | Low but useless | High and overlapping | Moderate and focused |
| Rebuild cost | Fast but pointless | Expensive (N projectors) | Proportional to real needs |
| Maintenance burden | Low (trivial copy) | High (N projectors per event) | Moderate |
| Field selection | Consumer must filter | Perfect fit | API layer selects fields |
| Staleness | N/A (same as write) | Multiple windows | One window per projection |

The principle: **design projections around consumer needs, not domain entities.
Combine data from multiple aggregates into the shape the consumer requires. Use
cache-backed projections for volatile key-value lookups and database-backed
projections for complex queries. When two consumers need similar data, prefer
one projection with optional fields over two separate ones.**

---

!!! tip "Related reading"
    **Patterns:**

    - [Design Events for Consumers](design-events-for-consumers.md) -- Events carry enough context for projectors to act independently.
    - [Design Small Aggregates](design-small-aggregates.md) -- Small aggregates affect projection design.

    **Concepts:**

    - [Projections](../concepts/building-blocks/projections.md) -- What projections are and how they fit in CQRS.
    - [Projectors](../concepts/building-blocks/projectors.md) -- How projectors maintain projections.

    **Guides:**

    - [Projections](../guides/consume-state/projections.md) -- Defining and configuring projections.
    - [Projectors](../guides/consume-state/projectors.md) -- Defining projectors and handling events.
