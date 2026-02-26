# Bridge the Eventual Consistency Gap in User Interfaces

## The Problem

In a CQRS architecture, writes and reads travel different paths. A user
submits an order, and the command flows through an application service (or
command handler) into the aggregate. The aggregate raises a domain event. A
projector eventually processes that event and updates the projection. Only then
does the read side reflect the new state.

In practice, the delay between command completion and projection update ranges
from tens of milliseconds to several seconds. During that window, the user
sees stale data. Consider this scenario:

```
1. Frontend sends POST /orders with order data
2. API calls OrderService.place_order() --> aggregate persisted, event raised
3. API returns HTTP 201 with order_id
4. Frontend navigates to GET /orders (the order list page)
5. The list is backed by an OrderSummary projection
6. The projector has not yet processed the OrderPlaced event
7. The new order does not appear in the list
```

The customer placed an order, received a success response, and cannot find
it. They refresh, create a duplicate, or contact support. The application
feels broken even though it is working as designed.

Teams encounter this gap and react in one of three ways, all problematic:

### Ignoring the gap

The team treats it as a non-issue: "The projection will catch up in a moment."
But users do not know about eventual consistency. They expect the data they
just submitted to appear immediately. Ignoring the gap creates support tickets,
duplicate submissions, and eroded trust.

### Adding `time.sleep()` hacks

```python
# Anti-pattern: sleeping and hoping
@app.post("/orders")
async def create_order(data: OrderData):
    service = OrderService()
    order = service.place_order(data.dict())

    # "Give the projector time to catch up"
    import time
    time.sleep(0.5)

    return {"order_id": order.order_id}
```

This is fragile. Half a second is not enough under load, two seconds is too
slow for normal traffic, and it blocks the API worker thread.

### Forcing synchronous processing everywhere

```toml
# Anti-pattern: disabling async processing in production
[event_processing]
default = "sync"
```

This eliminates the gap by running projectors inline during the commit, but
defeats the purpose of CQRS. Write latency includes every handler in the
chain, and failures cascade back to the caller. Synchronous processing is
valuable for **testing** but should not be the production strategy.

---

## The Pattern

There is no single solution because the gap's impact depends on context.
A periodically refreshing dashboard tolerates seconds of staleness; an order
confirmation page does not. Three strategies address the gap at different
levels:

### 1. Optimistic UI (frontend strategy)

The frontend immediately displays the expected state after a successful
command, without waiting for the read side. The next time the frontend
fetches data from the read side, it either confirms the optimistic state
or corrects it.

**Best for:** actions where the success response from the write side is
sufficient to predict the read-side state. Order placement, status changes,
profile updates.

**Not suitable for:** actions where the read-side result depends on
server-side computation that the frontend cannot predict (e.g., pricing
calculations, inventory checks that affect what is displayed).

### 2. Return write-side result (application service strategy)

The application service returns the aggregate's state directly from the
`@use_case` method. The frontend uses this write-side result for the immediate
display and falls back to projection reads for subsequent views.

**Best for:** single-entity views (order detail, profile page) where the
API response after the write can carry the data the UI needs.

**Not suitable for:** list views or dashboards that aggregate data across
multiple entities. The write side returns one aggregate; the list needs many.

### 3. Version polling (coordination strategy)

The write endpoint returns the aggregate's `_version` alongside the entity
data. The frontend passes this version to the read endpoint, which polls the
projection until its version matches or exceeds the expected version -- or
until a timeout.

**Best for:** critical transitions where the UI must show the confirmed
read-side state (e.g., payment confirmation page, shipping status).

**Not suitable for:** high-frequency actions where the polling overhead is
disproportionate to the consistency requirement.

### Choosing a strategy

| Situation | Strategy | Why |
|-----------|----------|-----|
| User navigates to a list after creating an item | Optimistic UI | Frontend inserts the new item locally |
| User sees a detail page after submitting a form | Return write-side result | API response carries everything the detail page needs |
| User must see confirmed state (payment, shipping) | Version polling | Guarantees the read side has caught up |
| Dashboard with periodic refresh | None needed | Natural refresh cycle absorbs the delay |
| Internal admin tool, low traffic | Synchronous test mode | Simplicity outweighs scalability |

---

## Applying the Pattern

The following examples use an e-commerce domain. First, the shared domain
elements that all three strategies build on:

```python
from protean.fields import Auto, DateTime, Float, Identifier, Integer, String

from protean import handle
from protean.core.application_service import use_case, BaseApplicationService
from protean.core.projector import on
from protean.globals import current_domain


@domain.event(part_of="Order")
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    customer_name = String(required=True)
    total = Float(required=True)
    item_count = Integer(required=True)
    placed_at = DateTime(required=True)


@domain.aggregate
class Order:
    order_id = Auto(identifier=True)
    customer_id = Identifier(required=True)
    customer_name = String(required=True)
    total = Float(default=0.0)
    item_count = Integer(default=0)
    status = String(default="draft")
    placed_at = DateTime()

    def place(self) -> None:
        self.status = "placed"
        from datetime import datetime, timezone
        self.placed_at = datetime.now(timezone.utc)
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            total=self.total,
            item_count=self.item_count,
            placed_at=self.placed_at,
        ))


@domain.projection
class OrderSummary:
    order_id = Identifier(identifier=True)
    customer_id = Identifier()
    customer_name = String()
    total = Float()
    item_count = Integer()
    status = String()
    placed_at = DateTime()


@domain.projector(projector_for=OrderSummary, aggregates=[Order])
class OrderSummaryProjector:

    @on(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced) -> None:
        repo = current_domain.repository_for(OrderSummary)
        repo.add(OrderSummary(
            order_id=event.order_id,
            customer_id=event.customer_id,
            customer_name=event.customer_name,
            total=event.total,
            item_count=event.item_count,
            status="placed",
            placed_at=event.placed_at,
        ))
```

---

### Strategy 1: Optimistic UI

The application service returns the aggregate after the write. The API
forwards enough data for the frontend to display optimistically.

```python
@domain.application_service(part_of=Order)
class OrderService(BaseApplicationService):

    @use_case
    def place_order(self, order_data: dict) -> Order:
        order = Order(**order_data)
        order.place()
        repo = current_domain.repository_for(Order)
        repo.add(order)
        return order
```

The API endpoint returns the write-side data:

```python
@app.post("/orders")
async def create_order(data: OrderData):
    service = OrderService()
    order = service.place_order(data.dict())

    # Return enough data for the frontend to display immediately
    return {
        "order_id": order.order_id,
        "customer_name": order.customer_name,
        "total": order.total,
        "status": order.status,
        "placed_at": order.placed_at.isoformat(),
    }, 201
```

The frontend receives this response and inserts it directly into its local
state (React state, Vuex store, Redux store) without waiting for a read-side
fetch. On the next background refresh, the projection data replaces the
optimistic entry. If the projection has not caught up yet, the optimistic
data remains visible until it does.

The key insight: the frontend does not poll or wait. It uses the write-side
response as the immediate truth and lets the projection catch up in the
background.

!!! note "When optimistic UI breaks down"
    Optimistic UI works when the frontend can predict the read-side state from
    the write-side response. It breaks down when:

    - The projection includes data from other aggregates (e.g., a warehouse
      assignment computed by an event handler). The frontend cannot predict this.
    - Server-side validation might reject the command after the API returns. If
      using async command processing, the command might fail downstream.
    - Multiple users view the same list. Other users will not see the optimistic
      entry until the projection updates.

---

### Strategy 2: Return write-side result

When the UI navigates to a detail page after a write, the application service
can return the aggregate's state directly. The frontend uses this for the
initial render and switches to projection reads for subsequent loads.

```python
@domain.application_service(part_of=Order)
class OrderService(BaseApplicationService):

    @use_case
    def place_order(self, order_data: dict) -> Order:
        order = Order(**order_data)
        order.place()
        repo = current_domain.repository_for(Order)
        repo.add(order)
        return order

    @use_case
    def get_order(self, order_id: str) -> Order:
        """Read from the write side when immediate consistency is needed."""
        repo = current_domain.repository_for(Order)
        return repo.get(order_id)
```

The API layer provides two read paths: one from the write side (for the
immediate post-write redirect) and one from the projection (for normal reads):

```python
@app.post("/orders")
async def create_order(data: OrderData):
    service = OrderService()
    order = service.place_order(data.dict())

    # Return the write-side state directly
    return {
        "order_id": order.order_id,
        "customer_name": order.customer_name,
        "total": order.total,
        "item_count": order.item_count,
        "status": order.status,
        "placed_at": order.placed_at.isoformat(),
        "_version": order._version,
    }, 201


@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    """Normal read path -- from the projection."""
    view = domain.view_for(OrderSummary)
    summary = view.get(order_id)
    return summary.to_dict()
```

The frontend uses the POST response data for the initial detail page render
and switches to the projection-backed GET endpoint for subsequent loads. This
strategy is particularly effective because `@use_case` methods naturally
return the aggregate -- the API layer simply passes it through.

!!! warning "Write-side reads are not free"
    Reading from the aggregate's repository means querying the write database.
    This is fine for the immediate post-write response (you just wrote to that
    database). But do not use write-side reads as a general replacement for
    projections. The write model is not optimized for read queries -- it may
    lack the indexes, denormalization, or shaping that projections provide.

---

### Strategy 3: Version polling

For critical transitions where the user must see confirmed read-side state,
return the aggregate's `_version` from the write endpoint and have the
frontend poll the read endpoint until the projection catches up.

The application service returns the aggregate with its version:

```python
@domain.application_service(part_of=Order)
class OrderService(BaseApplicationService):

    @use_case
    def place_order(self, order_data: dict) -> Order:
        order = Order(**order_data)
        order.place()
        repo = current_domain.repository_for(Order)
        repo.add(order)
        return order
```

The API endpoint returns `_version` in the response:

```python
@app.post("/orders")
async def create_order(data: OrderData):
    service = OrderService()
    order = service.place_order(data.dict())

    return {
        "order_id": order.order_id,
        "status": order.status,
        "_version": order._version,
    }, 201


@app.get("/orders/{order_id}")
async def get_order(order_id: str, min_version: int | None = None):
    """Read from projection, optionally waiting for a minimum version.

    If min_version is provided and the projection has not caught up,
    return 202 Accepted to signal the client to retry.
    """
    view = domain.view_for(OrderSummary)
    try:
        summary = view.get(order_id)
    except ObjectNotFoundError:
        if min_version is not None:
            # Projection has not created this record yet
            return {"status": "pending"}, 202
        raise

    # Check if the projection is at the expected version
    # (projection version tracking depends on your schema)
    if min_version is not None and summary._version < min_version:
        return {"status": "pending"}, 202

    return summary.to_dict()
```

The frontend extracts `_version` from the POST response, then polls the GET
endpoint with `?min_version=N`. On each poll:

- **HTTP 200** means the projection has caught up -- use the response body.
- **HTTP 202** means "not ready yet" -- wait with exponential backoff and retry.
- After a maximum number of attempts, fall back to the write-side data or
  show a "processing" indicator.

!!! note "Version tracking in projections"
    Protean's aggregates carry `_version` automatically. To use version polling,
    your projection needs to store the source aggregate's version. Include a
    `version` field in your projection and populate it from the event metadata
    in the projector. The exact mechanism depends on your event schema design.

---

### Development and testing: synchronous mode

During development and testing, the eventual consistency gap is a nuisance
that slows feedback cycles. Protean supports synchronous event processing
that eliminates the gap entirely for non-production environments:

```toml
# domain.toml -- development/test configuration
[event_processing]
default = "sync"
```

Or in test fixtures:

```python
import pytest
from protean import Domain


@pytest.fixture
def domain():
    domain = Domain(__file__, "Testing")
    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    with domain.domain_context():
        domain.init()
        yield domain
```

With synchronous processing, projectors run inline during the `UnitOfWork`
commit. The projection is updated before the `@use_case` method returns,
so there is no gap:

```python
def test_order_appears_in_projection_immediately(domain):
    # Arrange
    service = OrderService()

    # Act -- place the order (projector runs synchronously)
    order = service.place_order({
        "customer_id": "cust-123",
        "customer_name": "Alice",
        "total": 99.99,
        "item_count": 3,
    })

    # Assert -- projection is already updated
    view = domain.view_for(OrderSummary)
    summary = view.get(order.order_id)
    assert summary.status == "placed"
    assert summary.total == 99.99
```

!!! warning "Synchronous processing is for development and testing only"
    In production, synchronous event processing means every projector and
    event handler runs inside the write transaction. A slow or failing handler
    blocks the API response and can cascade failures back to the caller. Use
    asynchronous processing in production and apply one of the three UI
    strategies described above.

---

## Anti-Patterns

### The `time.sleep()` bridge

```python
# Anti-pattern: arbitrary sleep hoping the projector catches up
@app.post("/orders")
async def create_order(data: OrderData):
    service = OrderService()
    order = service.place_order(data.dict())

    import time
    time.sleep(1)  # Hope for the best

    view = domain.view_for(OrderSummary)
    summary = view.get(order.order_id)
    return summary.to_dict()
```

Problems:

- **Unpredictable.** One second is enough under light load, not enough under
  heavy load, and wasteful when the projector finishes in 50ms.
- **Blocks the worker.** An async API worker sitting in `time.sleep()` is not
  serving other requests.
- **No feedback.** If the projector fails, the sleep completes and the
  subsequent `view.get()` raises `ObjectNotFoundError` with no explanation.

Use optimistic UI or version polling instead. Both provide deterministic
behavior regardless of load.

### Forcing synchronous processing in production

```toml
# Anti-pattern: sync processing in production to avoid the gap
[event_processing]
default = "sync"
```

This eliminates the consistency gap but introduces worse problems:

- **Write latency includes all handlers.** The user waits for every projector
  and event handler to complete before seeing a response.
- **Handler failures cascade.** A bug in a projector causes the write to fail.
- **No backpressure isolation.** A slow analytics handler degrades the order
  placement endpoint.

### Ignoring the gap entirely

```python
# Anti-pattern: pretending the gap does not exist
@app.post("/orders")
async def create_order(data: OrderData):
    service = OrderService()
    service.place_order(data.dict())
    return {"status": "created"}, 201

# Frontend immediately fetches the order list
# New order may or may not appear
# User refreshes repeatedly, creates duplicates, contacts support
```

The gap exists by design. Ignoring it transfers the confusion to the user.
During deployment, load spikes, or projector errors the delay will be
noticeable. Plan for it.

### Read-your-writes via direct database queries

```python
# Anti-pattern: bypassing the projection to query the write database
@app.get("/orders")
async def list_orders():
    repo = domain.repository_for(Order)
    orders = repo._dao.query.all().items
    return [o.to_dict() for o in orders]
```

This defeats the purpose of projections. The write model's table lacks the
indexes, denormalization, and field shaping that projections provide, and it
couples read and write schemas together.

---

## Summary

| Aspect | Optimistic UI | Return Write-Side Result | Version Polling |
|--------|--------------|--------------------------|-----------------|
| **Where it runs** | Frontend | Application service + API | Frontend + API |
| **Consistency guarantee** | Eventual (predicted) | Immediate (write-side) | Confirmed (read-side) |
| **Latency** | Zero (no extra calls) | Zero (data in response) | Variable (polling) |
| **Complexity** | Frontend state management | Minimal backend change | Polling logic + timeout |
| **Works for list views** | Yes (local insert) | No (single entity) | Yes (with projection query) |
| **Works for detail views** | Yes | Yes (best fit) | Yes |
| **Handles server-side computation** | No | Partially | Yes |
| **Multiple users see same data** | No (local only) | No (caller only) | Yes (projection is shared) |
| **Best for** | Most common case | Post-write redirects | Critical confirmations |

The strategies are not mutually exclusive. A typical application uses all three:

- **Optimistic UI** for most interactions (add to cart, update profile)
- **Return write-side result** for post-write detail pages (order confirmation)
- **Version polling** for critical state transitions (payment confirmation,
  shipping status)

The principle: **eventual consistency is a feature, not a bug. The gap between
write and read is by design -- it enables independent scaling, failure isolation,
and read-side optimization. Bridge the gap in the UI layer with explicit
strategies rather than hiding it with sleeps, forcing synchronous processing,
or pretending it does not exist.**

---

!!! tip "Related reading"
    **Patterns:**

    - [Design Projection Granularity](projection-granularity.md) -- Design projections around consumer needs.
    - [Treat Projection Rebuilds as a Deployment Strategy](projection-rebuilds-as-deployment.md) -- Projection lifecycle management.

    **Concepts:**

    - [CQRS](../concepts/architecture/cqrs.md) -- Separating read and write responsibilities.

    **Guides:**

    - [Application Services](../guides/change-state/application-services.md) -- Synchronous use cases returning results.
    - [Projections](../guides/consume-state/projections.md) -- Read-optimized views.
