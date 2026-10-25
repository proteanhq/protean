# Query Handler Anti-Patterns

## Using `@handle` instead of `@read`

Command and event handlers use `@handle`; query handlers use `@read`. Protean
rejects `@handle` on a query handler method with `IncorrectUsageError`:
``Method `get_by_id` in Query Handler `OrderQueryHandler` is decorated with
`@handle`, which wraps execution in a UnitOfWork. Query Handler methods must be
stateless reads. Use `@read` ...``.

```python
# fragment
# WRONG: @handle wraps a UoW and expects side effects
@handle(GetOrderById)
def get_by_id(self, query): ...
```

## Forgetting to return

A query handler's whole purpose is to return data. A method that reads but does
not `return` hands `None` back to the caller.

```python
# fragment
# WRONG
@read(GetOrderById)
def get_by_id(self, query):
    current_domain.view_for(OrderSummary).get(query.order_id)  # no return
```

## Side effects in a read

Reads must be free of mutation and persistence. Never write from a query handler.

```python
# fragment
# WRONG: mutating during a read
@read(GetOrderById)
def get_by_id(self, query):
    order = current_domain.view_for(OrderSummary).get(query.order_id)
    order.last_viewed_at = utcnow()
    current_domain.repository_for(OrderSummary).add(order)  # NO
    return order
```

If a read needs to record that it happened, raise that as a command/event from
the appropriate write-side flow, outside the query handler.

## Reading the aggregate instead of the projection

Query handlers serve the read model. Loading the write-side aggregate couples the
read path to the consistency boundary and the aggregate's shape.

```python
# fragment
# WRONG: reading the write model
@read(GetOrderById)
def get_by_id(self, query):
    return current_domain.repository_for(Order).get(query.order_id)
```

## Two handlers for one query

Each query is answered by exactly one `@read` method. A second
`@read(GetOrderById)` in the same handler raises `NotSupportedError`: `Query
GetOrderById cannot be handled by multiple handlers`. Split the read into
distinct queries instead.
