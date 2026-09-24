---
name: repository
description: Define a Protean repository - the persistence abstraction for aggregates in Domain-Driven Design. Repositories provide a collection-oriented interface to load and persist aggregates, hiding database details behind a clean domain API. Protean provides a default repository automatically for every aggregate; custom repositories add domain-specific queries or database-specific optimizations. Use when you need to persist an aggregate, load an aggregate, write a custom repository, add a custom query, override the default repository, connect to a specific database, or implement the repository pattern. Repositories always belong to an aggregate and respect Unit of Work transactional semantics.
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
---

# Repository

## Key concepts

Repositories are the **gateway between your domain model and the persistence layer**. In DDD, repositories represent a collection of aggregates — you `add` to the collection and `get` from it, without exposing database internals to the domain.

**Protean provides a default repository for every aggregate automatically.** You only need a custom repository when you want to add custom query methods or database-specific optimizations.

## Basic structure: Default repository (no code needed)

```python
@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    status: String(default="draft")

# No repository class needed — Protean auto-generates one
# Use it directly:
repo = domain.repository_for(Order)
repo.add(order)
order = repo.get("ORD-001")
```

## Basic structure: Custom repository

```python
@domain.repository(part_of=Order)
class OrderRepository:
    def find_placed_orders(self):
        return self.query.filter(status="placed").all()

    def find_by_customer(self, customer_id):
        return self.query.filter(customer_id=customer_id).all()
```

## Key rules

1. **Repositories always belong to an aggregate** - Specify `part_of` with the aggregate **class**: `@domain.repository(part_of=Order)`. Define the aggregate before the repository so the class resolves. Unlike command/event handlers, repositories require the resolved class — a string reference (`part_of="Order"`) is not accepted and raises an error at registration
2. **Default repository is automatic** - Every aggregate gets `add()` and `get()` for free; only write a custom repository when you need custom queries
3. **Persist at the aggregate level** - Repositories save the entire aggregate including enclosed entities and value objects; never persist entities separately
4. **Use `add()` for both create and update** - The repository's `add()` method handles both new and modified aggregates (collection semantics)
5. **Use `get()` to load by identifier** - Loads the aggregate with all its children from the persistence store
6. **Use the query helpers for custom queries** - Inside a custom repository, use `self.query` for filtering, sorting, and paging, and `self.find_by()`, `self.find()`, and `self.exists()` for single lookups and existence checks. `self._dao` stays available as an internal escape hatch for infrastructure work
7. **Repositories respect Unit of Work** - When inside a UoW (e.g., command handlers), changes are committed atomically at UoW commit
8. **Database option controls provider binding** - Use `database` option to lock a repository to a specific database type (default is `"ALL"`)
9. **Children are synced automatically** - HasMany/HasOne child entities are persisted/removed automatically when the aggregate is added
10. **Custom repos inherit base methods** - Custom repositories still have `add()` and `get()` from `BaseRepository`; only add new methods

## Repository options

| Option | Purpose | Required | Default |
|--------|---------|----------|---------|
| `part_of` | Associate repository with an aggregate class | Yes | None |
| `database` | Lock repository to a specific database type | No | `"ALL"` |

## Quick example: Custom repository with queries

```python
@domain.aggregate
class Product:
    product_id: Identifier(identifier=True)
    name: String(required=True)
    category: String()
    price: Float()
    is_active: Boolean(default=True)

@domain.repository(part_of=Product)
class ProductRepository:
    def find_by_category(self, category):
        return self.query.filter(category=category).all()

    def find_active(self):
        return self.query.filter(is_active=True).all()

    def find_affordable(self, max_price):
        return self.query.filter(price__lte=max_price).all()
```

## Counting and null-aware queries

When you only need *how many* rows match, use `count()` — it issues a flat
`COUNT` without materializing entities, so it is cheaper than `len(query.all())`:

```python
@domain.repository(part_of=Order)
class OrderRepository:
    def open_count(self) -> int:
        return self.query.filter(status="open").count()
```

Filter on whether a field is set with the `isnull` lookup:

```python
# Orders with no assignee (assignee IS NULL)
self.query.filter(assignee__isnull=True).all().items
# Orders that have an assignee (assignee IS NOT NULL)
self.query.filter(assignee__isnull=False).all().items
```

When you need the page of items but not the total match count, pass
`with_total=False` so the adapter can skip the separate count round-trip:

```python
items = self.query.filter(status="open").all(with_total=False).items
```

## Using repositories in handlers

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def handle_place_order(self, command):
        order = Order(order_id=command.order_id, customer_id=command.customer_id)
        order.place()
        # Persist via repository — UoW handles transactional commit
        domain.repository_for(Order).add(order)

    @handle(CancelOrder)
    def handle_cancel(self, command):
        # Load existing aggregate
        order = domain.repository_for(Order).get(command.order_id)
        order.cancel()
        domain.repository_for(Order).add(order)
```

## Common mistakes

### Writing a repository when the default suffices

```python
# Unnecessary! Protean provides this automatically
@domain.repository(part_of=Order)
class OrderRepository:
    pass  # No custom methods — just use the default
```

Instead: Only create a custom repository when you need custom query methods

### Persisting child entities separately

```python
# Wrong! Never persist entities directly
@domain.repository(part_of=LineItem)  # LineItem is an entity, not an aggregate
class LineItemRepository:
    pass
```

Instead: Persist at the aggregate level; child entities are synced automatically

```python
order.add_items(LineItem(product_id="PROD-1", quantity=2))
domain.repository_for(Order).add(order)  # LineItem is saved with the order
```

### Forgetting part_of

```python
@domain.repository  # Wrong! Missing part_of
class OrderRepository:
    pass
```

Instead: Always specify part_of with the aggregate class

```python
@domain.repository(part_of=Order)
class OrderRepository:
    pass
```

### Wrapping repository calls in manual UnitOfWork inside handlers

```python
@handle(PlaceOrder)
def handle_place_order(self, command):
    with UnitOfWork():  # Unnecessary! Handler has implicit UoW
        order = Order(...)
        domain.repository_for(Order).add(order)
```

Instead: Let the implicit UnitOfWork handle transactional behavior

## Detailed references

### Core Concepts
- [Default Repository](references/default-repository.md) - How Protean auto-generates repositories
- [Custom Queries](references/custom-queries.md) - Writing domain-specific query methods using DAO
- [Database-Specific Repositories](references/database-specific.md) - Binding repositories to specific databases
- [Unit of Work Integration](references/unit-of-work.md) - Transactional semantics and UoW
- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

### Complete Examples
- [Default Repository](assets/repository_default.py) - Using the auto-generated repository
- [Custom Repository](assets/repository_custom.py) - Custom repository with domain-specific queries
- [Repository with Children](assets/repository_with_children.py) - Persisting aggregates with child entities
- [Database-Specific Repository](assets/repository_with_database.py) - Per-database repository binding
- [Repository with Unit of Work](assets/repository_with_uow.py) - Explicit UoW usage outside handlers
- [Counting and Null-Aware Queries](assets/repository_counting_and_nulls.py) - `count()`, `all(with_total=False)`, and the `isnull` lookup

### Related Skills
- `aggregate` - Repositories persist aggregates
- `command-handler` - Command handlers use repositories to load and persist aggregates
- `event-handler` - Event handlers use repositories for cross-aggregate coordination
- `entity` - Entities enclosed within aggregates are persisted automatically via repositories

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
