# Anti-patterns

The examples on this page use these aggregates and this command:

```python
@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    status: String(max_length=20, default="draft")
    items = HasMany("LineItem")

    def place(self):
        self.status = "placed"


@domain.aggregate
class Inventory:
    product_id: Identifier(identifier=True)
    reserved: Integer(default=0)

    def reserve(self, quantity):
        self.reserved += quantity


@domain.command(part_of=Order)
class PlaceOrder:
    order_id: Identifier(identifier=True)
    product_id: Identifier(required=True)
    quantity: Integer(default=1)
```

## 1. Creating a Repository for Child Entities

**Wrong**: Creating a repository for an entity that's enclosed within an aggregate.

```python
# fragment
@domain.entity(part_of="Order")
class LineItem:
    item_id: Identifier(identifier=True)
    product_id: String(required=True)

@domain.repository(part_of=LineItem)  # Wrong! LineItem is an entity, not an aggregate
class LineItemRepository:
    pass
```

**Why it's wrong**: Registration raises `IncorrectUsageError`: "Repository `LineItemRepository` can only be associated with an Aggregate". An entity is saved with its aggregate.

**Instead**: Persist child entities through the aggregate's repository.

```python
@domain.entity(part_of=Order)
class LineItem:
    product_id: String(required=True, max_length=50)
    quantity: Integer(default=1)


domain.init(traverse=False)

with domain.domain_context():
    order = Order(order_id="ORD-001")
    order.add_items(LineItem(product_id="PROD-1", quantity=2))
    domain.repository_for(Order).add(order)  # LineItem saved with the order
```

## 2. Wrapping Handler Code in Manual UnitOfWork

**Wrong**: Manually creating a UoW inside a command handler.

```python
# fragment
@handle(PlaceOrder)
def handle_place_order(self, command):
    with UnitOfWork():  # Unnecessary! Handler already has implicit UoW
        order = Order(order_id=command.order_id)
        domain.repository_for(Order).add(order)
```

**Why it's wrong**: `@handle` already wraps every handler call in its own Unit of Work, which is one real database transaction on a provider with transactions, such as the SQL databases. A Unit of Work started while another is active joins the outer one: there are no savepoints, so its commit does nothing, and only the handler's Unit of Work commits. A rollback inside it dooms the whole transaction. On a version conflict, `@handle` re-runs the whole handler body, manual block included: with the default `max_retries=3`, the body runs up to 4 times in total. See ADR-0027 ([The Unit of Work is a real database transaction](https://docs.proteanhq.com/adr/0027-unit-of-work-is-a-real-transaction/)) and ADR-0031 ([A handler method persists or calls out, never both](https://docs.proteanhq.com/adr/0031-handlers-persist-or-call-out/)).

**Instead**: Write the handler body without the `with` block.

## 3. Forgetting `part_of` on Repository

**Wrong**: Declaring a repository without associating it with an aggregate.

```python
# fragment
@domain.repository  # Missing part_of!
class OrderRepository:
    pass
```

**Why it's wrong**: Registration raises `IncorrectUsageError`: "Repository `OrderRepository` should be associated with an Aggregate".

**Instead**: Pass `part_of`, as in `@domain.repository(part_of=Order)`.

## 4. Changing Two Aggregates in One Transaction

**Wrong**: Loading and persisting two different aggregates in one handler.

```python
# fragment
@handle(PlaceOrder)
def handle_place_order(self, command):
    order = Order(order_id=command.order_id)
    domain.repository_for(Order).add(order)

    # Wrong! Modifying a different aggregate in the same handler
    inventory = domain.repository_for(Inventory).get(command.product_id)
    inventory.reserve(command.quantity)
    domain.repository_for(Inventory).add(inventory)
```

**Why it's wrong**: A command handler should modify only ONE aggregate per transaction, even two instances of the same type. The Unit of Work can hold changes to several aggregates and commits them all, so nothing stops this code.

**Instead**: Raise an event and change the other aggregate in its own transaction.

```python
@handle(PlaceOrder)
def handle_place_order(self, command):
    order = Order(order_id=command.order_id)
    order.place()  # Raises OrderPlaced event
    domain.repository_for(Order).add(order)
    # An event handler reacts to OrderPlaced and issues a ReserveStock command;
    # Inventory's command handler reserves the stock in a transaction
    # separate from this one
```

## 5. Using Repository Outside Domain Context

**Wrong**: Using `domain.repository_for()` without initializing the domain.

```python
# fragment
domain = Domain()

@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)

# Missing domain.init() and domain_context!
repo = domain.repository_for(Order)  # Returns a repository
repo.add(Order(order_id="ORD-001"))  # AttributeError: providers
```

**Instead**: Initialize the domain and use a domain context.

```python
domain.init(traverse=False)
with domain.domain_context():
    repo = domain.repository_for(Order)
    repo.add(Order(order_id="ORD-002"))
```

## 6. Bypassing the Repository to Access the Database Directly

**Wrong**: Using the DAO or database connection directly from handler code.

```python
# fragment
@handle(PlaceOrder)
def handle_place_order(self, command):
    # Wrong! Bypassing the repository
    dao = domain.providers.get_dao(Order)
    dao.create(order_id=command.order_id, status="placed")
```

**Why it's wrong**: The repository handles Unit of Work integration, child syncing, version tracking and event dispatch. A direct DAO call skips all of them.

**Instead**: Use `domain.repository_for()`.

## Related
- [Default Repository](./default-repository.md): When no custom repo is needed
- [Custom Queries](./custom-queries.md): Writing proper query methods
- [Unit of Work Integration](./unit-of-work.md): Proper UoW usage
