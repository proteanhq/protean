---
description: Persistence patterns — repositories, command submission, and transaction boundaries
globs: "**/*.py"
---

# Persistence Patterns

## Access Repositories via `domain.repository_for()`

Always use `domain.repository_for(AggregateClass)` to obtain a repository. Inside handlers,
use `self.repository` (auto-injected). Never construct repositories manually:

```python
# In handler methods — use self.repository (auto-injected)
@handle(PlaceOrder)
def place_order(self, command):
    order = Order.create(buyer_id=command.buyer_id)
    self.repository.add(order)

# Outside handlers — use domain.repository_for()
with domain.domain_context():
    repo = domain.repository_for(Order)
    order = repo.get(order_id)
```

## `.add()` for Both Create and Update

Repositories use **collection semantics** — `.add()` handles both new aggregates and updates
to existing ones. There is no separate `.update()` or `.save()`:

```python
# Creating
order = Order.create(buyer_id=buyer_id)
self.repository.add(order)

# Updating (same method)
order = self.repository.get(order_id)
order.cancel()
self.repository.add(order)
```

## Persist at the Aggregate Level

Never persist entities directly — always persist through the aggregate root. Entities are
part of the aggregate's consistency boundary:

```python
# Good — persist the aggregate
order = self.repository.get(order_id)
order.add_line_item(product_id=product_id, quantity=2)
self.repository.add(order)  # Persists order + its line items

# Bad — persisting entity directly
line_item = LineItem(product_id=product_id, quantity=2)
some_repo.add(line_item)  # Entities don't have their own repositories
```

## Submit Commands via `domain.process()`

Always submit commands through `domain.process()`. Never call handlers directly:

```python
# Good
domain.process(PlaceOrder(buyer_id=buyer_id, items=items))

# In FastAPI endpoints
from protean.globals import current_domain
current_domain.process(PlaceOrder(buyer_id=buyer_id, items=items))

# Bad — calling handler directly
handler = OrderCommandHandler()
handler.place_order(command)  # Never do this
```

## One Aggregate Per Transaction

Each handler invocation is a single transaction operating on a single aggregate. For
cross-aggregate coordination, use domain events and eventual consistency:

```python
# Good — one aggregate per handler
@handle(PlaceOrder)
def place_order(self, command):
    order = Order.create(...)
    self.repository.add(order)
    # Order raises OrderPlaced event -> separate handler updates Inventory

# Bad — two aggregates in one handler
@handle(PlaceOrder)
def place_order(self, command):
    order = Order.create(...)
    inventory = other_repo.get(product_id)
    inventory.reserve(quantity)  # Don't modify another aggregate here
    self.repository.add(order)
    other_repo.add(inventory)
```

## API Endpoints Are Thin Adapters

FastAPI endpoints only translate HTTP requests into commands and call `current_domain.process()`.
No business logic, no repository access, no aggregate manipulation in endpoints:

```python
# Good — thin adapter
@app.post("/orders")
def create_order(request: CreateOrderRequest):
    result = current_domain.process(
        PlaceOrder(buyer_id=request.buyer_id, items=request.items),
        asynchronous=False,
    )
    return {"id": str(result.id)}

# Bad — business logic in endpoint
@app.post("/orders")
def create_order(request: CreateOrderRequest):
    repo = current_domain.repository_for(Order)
    order = Order(buyer_id=request.buyer_id)
    for item in request.items:
        order.add_line_item(item.product_id, item.quantity)
    repo.add(order)
```
