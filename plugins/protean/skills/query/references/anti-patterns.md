# Query Anti-Patterns

The examples on this page read from an `OrderSummary` projection through a
`SearchOrders` query:

```python
@domain.projection
class OrderSummary:
    order_id: Identifier(identifier=True)
    status: String(max_length=20)
    total: Integer(default=0)


@domain.query(part_of="OrderSummary")
class SearchOrders:
    status: String()
    min_total: Integer(default=0)
```

## Targeting an aggregate instead of a projection

Queries belong to the **read** side. Their `part_of` is a projection, never an
aggregate.

```python
# fragment
# WRONG: querying the write model
@domain.query(part_of="Order")
class GetOrderById:
    order_id: Identifier(required=True)
```

`domain.init()` rejects it. A query's `part_of` resolves only against
projections, so the aggregate name is left unresolved and init raises
`ConfigurationError`: ``Unresolved references in domain ...: `GetOrderById`
references `Order` via part_of``.

If no projection exists for the read you need, define one with the
`projection` and `projector` skills.

## Putting logic in the query

A query is a parameter object, not a place for behavior. It should not reach into
repositories, run filters, or compute results. That is the query handler's job.

```python
# fragment
# WRONG: query does the work
@domain.query(part_of="OrderSummary")
class GetOrderById:
    order_id: Identifier(required=True)

    def execute(self):  # No! Logic belongs in the handler
        return current_domain.view_for(OrderSummary).get(self.order_id)
```

Keep the query a pure DTO; dispatch it to a handler with `domain.dispatch()`.

## Associations and rich types

Queries take basic fields and value objects only. An association
(`HasOne`/`HasMany`/`Reference`) raises `IncorrectUsageError` when the class is
decorated: `Queries can only contain basic field types. Remove lines (HasMany)
from class SearchOrders`.

```python
# fragment
# WRONG
@domain.query(part_of="OrderSummary")
class SearchOrders:
    lines = HasMany("OrderLine")
```
