---
name: query-handler
description: Define a Protean query handler - a class that answers queries by reading from projections and returning results. Query handlers are the read-side counterpart to command handlers: they use the @read decorator (not @handle), are dispatched via domain.dispatch(), and RETURN values. They run with no Unit of Work and no side effects. A handler is associated with a projection via part_of and reads through current_domain.view_for(Projection). Use when you need to answer a query, implement the read side of CQRS, return data from a projection, wire a query to a result, or when the user asks to "create a query handler", "handle a query", "answer a read request", or "return data for a query". Each handler method is decorated with @read(QueryClass).
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
  diagnostic_codes:
    - QUERY_HANDLER_WITHOUT_QUERY
---

# Query Handler

A query handler answers queries: it receives a query DTO, reads from a projection, and **returns** the result. It is the read-side mirror of a command handler — but it uses `@read` instead of `@handle`, runs no Unit of Work, and always returns a value.

## Basic structure

```python
from protean import Domain, current_domain, read
from protean.fields import Identifier, String

domain = Domain()

@domain.projection
class OrderSummary:
    order_id: Identifier(identifier=True)
    status: String(max_length=20)

@domain.query(part_of="OrderSummary")
class GetOrderById:
    order_id: Identifier(required=True)

@domain.query_handler(part_of="OrderSummary")
class OrderQueryHandler:
    @read(GetOrderById)
    def get_by_id(self, query: GetOrderById):
        return current_domain.view_for(OrderSummary).get(query.order_id)
```

## Key rules

1. **part_of is the projection** - Associate the handler with the projection it reads: `@domain.query_handler(part_of="OrderSummary")` (the read model, not an aggregate)
2. **Use the `@read` decorator** - Each method is decorated `@read(QueryClass)` (the read-side counterpart to `@handle`); import it: `from protean import read`
3. **Handlers RETURN values** - Unlike command/event handlers, a query handler returns its result; `domain.dispatch(query)` hands that value back to the caller
4. **One method per query** - Each query type is answered by exactly one `@read` method
5. **Method signature is `(self, query)`** - The dispatched query instance is passed in
6. **No Unit of Work, no side effects** - Reads are stateless; never mutate state or persist from a query handler
7. **Read through `view_for`** - Use `current_domain.view_for(Projection)` to get a read-only query interface: `.get(id)`, `.query.filter(...).all()`, `.count()`, `.exists(id)`
8. **Dispatch with `domain.dispatch(query)`** - This routes the query to its handler and returns the result (synchronous)

## Handler options

| Option | Purpose | Required |
|--------|---------|----------|
| `part_of` | Associate the handler with a projection | Yes |

## Quick example: Multiple queries

```python
from protean import Domain, current_domain, read
from protean.fields import Identifier, String

domain = Domain()

@domain.projection
class OrderSummary:
    order_id: Identifier(identifier=True)
    status: String(max_length=20)

@domain.query(part_of="OrderSummary")
class GetOrderById:
    order_id: Identifier(required=True)

@domain.query(part_of="OrderSummary")
class ListOrdersByStatus:
    status: String(required=True)

@domain.query_handler(part_of="OrderSummary")
class OrderQueryHandler:
    @read(GetOrderById)
    def get_by_id(self, query: GetOrderById):
        return current_domain.view_for(OrderSummary).get(query.order_id)

    @read(ListOrdersByStatus)
    def list_by_status(self, query: ListOrdersByStatus):
        view = current_domain.view_for(OrderSummary)
        return view.query.filter(status=query.status).all().items
```

## Dispatching queries

```python
# Returns the handler's return value directly (synchronous)
order = domain.dispatch(GetOrderById(order_id="ORD-1"))
placed = domain.dispatch(ListOrdersByStatus(status="placed"))
```

## Reading through view_for

`current_domain.view_for(Projection)` returns a read-only interface:

```python
view = current_domain.view_for(OrderSummary)
view.get("ORD-1")                                  # single record by id
view.query.filter(status="placed").all().items     # filtered list
view.query.filter(status="placed").count()         # flat count
view.exists("ORD-1")                               # is there a record with this id?
```

## Common mistakes

### Using @handle instead of @read

```python
@domain.query_handler(part_of="OrderSummary")
class OrderQueryHandler:
    @handle(GetOrderById)  # Wrong! Query handlers use @read
    def get_by_id(self, query):
        ...
```

Instead: use `@read(QueryClass)`.

### Not returning a value

```python
@read(GetOrderById)
def get_by_id(self, query):
    current_domain.view_for(OrderSummary).get(query.order_id)  # Wrong! No return
```

Instead: `return` the result — the dispatcher hands it back to the caller.

### Mutating state in a query handler

```python
@read(GetOrderById)
def get_by_id(self, query):
    order = current_domain.view_for(OrderSummary).get(query.order_id)
    order.status = "viewed"  # Wrong! Reads must not mutate
    return order
```

Instead: queries are side-effect free. Change state through commands.

### Pointing part_of at an aggregate

```python
@domain.query_handler(part_of="Order")  # Wrong! Use the projection
class OrderQueryHandler:
    ...
```

Instead: `part_of` is the projection the handler reads from.

## Detailed references

- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

### Complete examples

- [Simple Query Handler](assets/query_handler_simple.py) - Projection, queries, handler, dispatch

### Related skills

- `query` - The read-intent DTO a handler answers
- `projection` - The read model the handler reads from
- `projector` - Populates the projection from domain events
- `command-handler` - The write-side counterpart (uses `@handle`, runs a UoW)

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
