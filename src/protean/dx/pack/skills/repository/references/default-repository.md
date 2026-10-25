# Default Repository

## Code

The complete implementation is in [assets/repository_default.py](../assets/repository_default.py).

## How It Works

### Accessing the Default Repository

The examples on this page use this aggregate:

```python
@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    customer_id: Identifier(required=True)
    status: String(max_length=20, default="draft")
    total_amount: Float(default=0.0)

    def place(self, total_amount):
        self.total_amount = total_amount
        self.status = "placed"
```

Ask the domain for the repository, inside a domain context:

```python
domain.init(traverse=False)

with domain.domain_context():
    repo = domain.repository_for(Order)
```

Protean resolves this by:
1. Checking if a custom repository is registered for `Order`
2. If not, dynamically creating an `OrderRepository` class inheriting from `BaseRepository`
3. Connecting it to the appropriate database provider

### The `add()` Method

```python
with domain.domain_context():
    repo = domain.repository_for(Order)

    order = Order(order_id="ORD-001", customer_id="CUST-123")
    repo.add(order)  # Creates the record

    order.place(total_amount=99.99)
    repo.add(order)  # Updates the record (same method)
```

The `add()` method:
- Checks if the aggregate is new or already persisted (via internal state tracking)
- For new aggregates: creates a new database record
- For existing aggregates: updates the existing record
- Automatically syncs child entities (HasMany/HasOne)
- Respects the active Unit of Work (if any)

### The `get()` Method

```python
with domain.domain_context():
    order = domain.repository_for(Order).get("ORD-001")
```

The `get()` method:
- Looks up the aggregate by its identifier field
- Returns the full aggregate with all child entities loaded
- Raises `ObjectNotFoundError` if no record matches

## Related
- [Custom Queries](./custom-queries.md): When the default isn't enough
- [Unit of Work Integration](./unit-of-work.md): Transactional behavior
- [Anti-patterns](./anti-patterns.md): Common mistakes
