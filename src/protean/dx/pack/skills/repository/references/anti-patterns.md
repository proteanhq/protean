# Anti-patterns

Common mistakes when working with Protean repositories and how to avoid them.

## 1. Creating a Repository for Child Entities

**Wrong**: Creating a repository for an entity that's enclosed within an aggregate.

```python
@domain.entity(part_of="Order")
class LineItem:
    item_id: Identifier(identifier=True)
    product_id: String(required=True)

@domain.repository(part_of=LineItem)  # Wrong! LineItem is an entity, not an aggregate
class LineItemRepository:
    pass
```

**Why it's wrong**: Repositories operate at the aggregate boundary. Entities enclosed within an aggregate are persisted automatically when the aggregate is saved. Creating separate repositories for entities breaks the transactional boundary and can lead to inconsistent state.

**Instead**: Persist child entities through the aggregate's repository.

```python
order.add_items(LineItem(product_id="PROD-1", quantity=2))
domain.repository_for(Order).add(order)  # LineItem saved with the order
```

## 2. Writing a Custom Repository Without Custom Methods

**Wrong**: Creating an empty custom repository when the default suffices.

```python
@domain.repository(part_of=Order)
class OrderRepository:
    pass  # No custom methods — why does this exist?
```

**Why it's wrong**: Protean auto-generates a repository with `add()` and `get()`. An empty custom repository adds code without adding value.

**Instead**: Only create custom repositories when you need custom query methods.

## 3. Wrapping Handler Code in Manual UnitOfWork

**Wrong**: Manually creating a UoW inside a command handler.

```python
@handle(PlaceOrder)
def handle_place_order(self, command):
    with UnitOfWork():  # Unnecessary! Handler already has implicit UoW
        order = Order(order_id=command.order_id)
        domain.repository_for(Order).add(order)
```

**Why it's wrong**: Command handlers and event handlers are already wrapped in an implicit UoW. Adding a manual one creates nested transactions, which can lead to unexpected behavior.

**Instead**: Let the implicit UoW handle it.

```python
@handle(PlaceOrder)
def handle_place_order(self, command):
    order = Order(order_id=command.order_id)
    domain.repository_for(Order).add(order)
```

## 4. Forgetting `part_of` on Repository

**Wrong**: Declaring a repository without associating it with an aggregate.

```python
@domain.repository  # Missing part_of!
class OrderRepository:
    pass
```

**Why it's wrong**: Protean raises `IncorrectUsageError` because repositories must be associated with an aggregate. The `part_of` parameter tells Protean which aggregate this repository manages.

**Instead**: Always specify `part_of`.

```python
@domain.repository(part_of=Order)
class OrderRepository:
    pass
```

## 5. Persisting Aggregates from Different Bounded Contexts in One Transaction

**Wrong**: Loading and persisting aggregates from two different aggregates in one handler.

```python
@handle(PlaceOrder)
def handle_place_order(self, command):
    order = Order(order_id=command.order_id)
    domain.repository_for(Order).add(order)

    # Wrong! Modifying a different aggregate in the same handler
    inventory = domain.repository_for(Inventory).get(command.product_id)
    inventory.reserve(command.quantity)
    domain.repository_for(Inventory).add(inventory)
```

**Why it's wrong**: A command handler should modify only ONE aggregate per operation. Cross-aggregate coordination should happen through domain events.

**Instead**: Use events for cross-aggregate side effects.

```python
@handle(PlaceOrder)
def handle_place_order(self, command):
    order = Order(order_id=command.order_id)
    order.place()  # Raises OrderPlaced event
    domain.repository_for(Order).add(order)
    # OrderPlaced event triggers InventoryHandler to reserve stock
```

## 6. Using Repository Outside Domain Context

**Wrong**: Using `domain.repository_for()` without initializing the domain.

```python
domain = Domain()

@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)

# Missing domain.init() and domain_context!
repo = domain.repository_for(Order)  # Will fail
```

**Instead**: Always initialize the domain and use a domain context.

```python
domain.init(traverse=False)
with domain.domain_context():
    repo = domain.repository_for(Order)
    repo.add(order)
```

## 7. Bypassing the Repository to Access the Database Directly

**Wrong**: Using the DAO or database connection directly from handler code.

```python
@handle(PlaceOrder)
def handle_place_order(self, command):
    # Wrong! Bypassing the repository
    dao = domain.providers.get_dao(Order)
    dao.create(order_id=command.order_id, status="placed")
```

**Why it's wrong**: Repositories encapsulate persistence logic and ensure proper UoW integration, child syncing, version tracking, and event dispatch. Bypassing them skips all these safeguards.

**Instead**: Always use `domain.repository_for()`.

## Related
- [Default Repository](./default-repository.md) - When no custom repo is needed
- [Custom Queries](./custom-queries.md) - Writing proper query methods
- [Unit of Work Integration](./unit-of-work.md) - Proper UoW usage
