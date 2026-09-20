# Query Anti-Patterns

## Targeting an aggregate instead of a projection

Queries belong to the **read** side. Their `part_of` is a projection, never an
aggregate.

```python
# WRONG — querying the write model
@domain.query(part_of="Order")
class GetOrderById:
    order_id: Identifier(required=True)

# RIGHT — querying a read model
@domain.query(part_of="OrderSummary")
class GetOrderById:
    order_id: Identifier(required=True)
```

If no projection exists for the read you need, define one (see the `projection`
and `projector` skills) rather than querying the aggregate directly.

## Putting logic in the query

A query is a parameter object, not a place for behavior. It should not reach into
repositories, run filters, or compute results — that is the query handler's job.

```python
# WRONG — query does the work
@domain.query(part_of="OrderSummary")
class GetOrderById:
    order_id: Identifier(required=True)

    def execute(self):  # No! Logic belongs in the handler
        return current_domain.view_for(OrderSummary).get(self.order_id)
```

Keep the query a pure DTO; dispatch it to a handler with `domain.dispatch()`.

## Mutating a query

Queries are immutable. Reusing one instance and "tweaking" it raises
`IncorrectUsageError`.

```python
# WRONG
q = SearchOrders(status="placed")
q.status = "shipped"  # IncorrectUsageError

# RIGHT — build a new query
q = SearchOrders(status="shipped")
```

## Associations and rich types

Queries take basic fields and value objects only. Associations
(`HasOne`/`HasMany`/`Reference`) are not allowed — they belong to aggregates.

```python
# WRONG
@domain.query(part_of="OrderSummary")
class SearchOrders:
    lines = HasMany("OrderLine")

# RIGHT — flat criteria
@domain.query(part_of="OrderSummary")
class SearchOrders:
    status: String()
    min_total: Integer(default=0)
```

## Imperative / vague names

Commands are imperative (`PlaceOrder`); queries are named for what they return.

```python
# WRONG
class FetchStuff: ...
class DoOrderLookup: ...

# RIGHT
class GetOrderById: ...
class SearchOrders: ...
class ListActiveCustomers: ...
```
