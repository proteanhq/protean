# Unit of Work

Each command handler method in Protean runs inside a Unit of Work, and a Unit of Work is one real database transaction on providers that support transactions.

## Overview

These decisions record this behavior:

- [ADR-0027 (The Unit of Work is a real database transaction)](https://docs.proteanhq.com/adr/0027-unit-of-work-is-a-real-transaction/)
- [ADR-0031 (A handler method persists or calls out, never both)](https://docs.proteanhq.com/adr/0031-handlers-persist-or-call-out/)

The examples on this page use these elements:

```python
from protean import handle
from protean.fields import Identifier, String

@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    product_id: Identifier()
    status: String(default="draft")

    def place(self):
        self.status = "placed"

@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    product_id: Identifier()
```

## How It Works

The `@handle` decorator wraps the handler method. Simplified, it does this:

```python
# fragment
# This is what Protean does internally (simplified)
class handle:
    def __call__(self, fn):
        @functools.wraps(fn)
        def wrapper(instance, target_obj):
            with UnitOfWork():
                return fn(instance, target_obj)
        return wrapper
```

The handler below runs its body inside one such `with UnitOfWork():` block:

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def handle_place_order(self, command: PlaceOrder):
        order = Order(order_id=command.order_id, product_id=command.product_id)
        order.place()
        domain.repository_for(Order).add(order)
```

A handler method that reaches no repository opens no transaction.

## What a Unit of Work Holds

Writes reach the database inside the transaction. The session flushes before each query, so reads in the same Unit of Work see earlier writes. Nothing is committed or visible to other connections until the Unit of Work commits, and a rollback undoes every write.

That holds on providers with real transactions, such as the SQL providers ADR-0027 covers. The in-memory provider keeps writes in the Unit of Work until it commits, so a rollback also leaves nothing behind. Elasticsearch has no transactions. There the Unit of Work logs a warning that commit and rollback are not atomic, and a rollback does not undo writes already sent.

A Unit of Work can hold changes to several aggregates. "One aggregate per transaction" is a design rule the Unit of Work does not enforce. The rule counts two instances of the same aggregate type as two roots. [Anti-patterns](./anti-patterns.md) section 4 shows how to change a second aggregate through an event and a command.

## Nested Units of Work

A Unit of Work started while another is active joins the outer one. There are no savepoints. Only the outermost Unit of Work commits or rolls back, and a rollback inside it dooms the whole transaction.

So a `with UnitOfWork():` inside a handler body joins the handler's own Unit of Work and adds nothing. Write the body directly, as `OrderCommandHandler` above does.

## Retries on Version Conflicts

When a save hits a version conflict, because another writer changed the same aggregate first, Protean raises `ExpectedVersionError`. `@handle` then re-runs the whole handler body. The default is `max_retries=3`, so the body runs up to 4 times in total. The wait between runs doubles each time, from 0.05 seconds up to a cap of 1 second. The retries stop early if the next run would start after the command's deadline. Change these settings, or turn the retry off, under `server.version_retry` in the domain config.

Each run opens its own Unit of Work. A handler that runs inside an outer Unit of Work does not retry. This happens when another handler or a use case calls `domain.process()` synchronously. The handler's Unit of Work joins the outer one, so a failed run has already doomed the outer transaction. The conflict goes up instead: an enclosing handler re-runs the whole chain in a fresh Unit of Work, and a use case passes it to its caller.

Keep the body safe to re-run. Do not call an external system after the first repository access: a retry calls it again, and the call holds the transaction open while it waits. ADR-0031 covers this, and `check` reports it as `HANDLER_PERSISTS_AND_CALLS_OUT`.

## Error Rollback

If an exception occurs within the handler method, the Unit of Work rolls back, and no partial changes are persisted:

```python
@domain.command(part_of="Order")
class PlaceOrderIfInStock:
    order_id: Identifier(required=True)
    product_id: Identifier(required=True)

def validate_inventory(product_id):
    if product_id == "OUT-OF-STOCK":
        raise ValueError(f"No stock for {product_id}")

@domain.command_handler(part_of=Order)
class StockCheckedOrderHandler:
    @handle(PlaceOrderIfInStock)
    def handle_place_order(self, command: PlaceOrderIfInStock):
        order = Order(order_id=command.order_id, product_id=command.product_id)
        order.place()
        domain.repository_for(Order).add(order)
        # If this line raises, the order addition above is rolled back
        validate_inventory(command.product_id)

domain.init(traverse=False)

with domain.domain_context():
    try:
        domain.process(
            PlaceOrderIfInStock(order_id="ORD-001", product_id="OUT-OF-STOCK"),
            asynchronous=False,
        )
    except ValueError:
        pass

    assert domain.repository_for(Order).query.filter(order_id="ORD-001").all().total == 0
```

## Related

- [Loading Aggregates](./loading-aggregates.md): How to load aggregates in handlers
- [Error Handling](./error-handling.md): Custom error handling with handle_error
- [Anti-patterns](./anti-patterns.md): Common Unit of Work mistakes
