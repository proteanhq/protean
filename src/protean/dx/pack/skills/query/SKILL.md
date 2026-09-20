---
name: query
description: Define a Protean query - an immutable DTO representing a read intent against a projection (read model). Queries carry the parameters needed to fetch data on the read side of CQRS and are answered by query handlers via domain.dispatch(). Queries are associated with a projection (not an aggregate) and are named for what they fetch (GetOrderById, SearchOrders, ListActiveUsers). Use when you need to define a read request, model a query parameter object, build the read side of CQRS, or when the user asks to "create a query", "define a query", "add a read query", "fetch data by criteria", or "query a projection". Queries are immutable, validated at construction, and contain only basic field types.
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
---

# Query

A query is an immutable DTO that carries a **read intent** — the parameters needed to fetch data from a projection. Queries are the read-side counterpart to commands: a command asks to *change* state, a query asks to *read* it.

## Basic structure

A query is defined with `@domain.query(part_of="<Projection>")`:

```python
from protean import Domain
from protean.fields import Identifier, String

domain = Domain()

@domain.projection
class OrderSummary:
    order_id: Identifier(identifier=True)
    customer_name: String(max_length=100)

@domain.query(part_of="OrderSummary")
class GetOrderById:
    order_id: Identifier(required=True)
```

## Key rules

1. **Queries are associated with a projection** - Specify `part_of` with the projection (read model) the query targets, not an aggregate: `@domain.query(part_of="OrderSummary")`
2. **Queries carry read intent** - They describe what to fetch, named for the result: `GetOrderById`, `SearchOrders`, `ListActiveUsers` (not imperative like commands)
3. **Queries are immutable** - Setting a field after construction raises `IncorrectUsageError`; create a new instance instead
4. **Validated at construction** - Missing/invalid fields raise `ValidationError` immediately, before dispatch
5. **Basic field types only** - Fields are simple types (String, Integer, Float, Boolean, Date, DateTime, Identifier) plus value objects; no `HasOne`, `HasMany`, or `Reference`
6. **Queries are answered by query handlers** - Define a `query_handler` and dispatch with `domain.dispatch(query)` (see the `query-handler` skill)
7. **Queries have no side effects** - Dispatch never mutates state or runs a Unit of Work; reads are stateless
8. **Lightweight DTOs** - Unlike commands/events, queries carry no metadata, stream, or event-store concerns

## Fields and options

| Field/Option | Purpose | Required |
|--------------|---------|----------|
| `part_of` | Associate the query with a projection | Yes (unless abstract) |
| `abstract` | Mark as an abstract base query | No |

### Supported field types

```python
from protean.fields import (
    String, Integer, Float, Boolean,
    DateTime, Date, Identifier,
    List, Dict, ValueObject,
)
```

Queries cannot use `HasOne`, `HasMany`, or `Reference` fields.

## Quick example

```python
from protean import Domain
from protean.fields import Identifier, Integer, String

domain = Domain()

@domain.projection
class OrderSummary:
    order_id: Identifier(identifier=True)
    customer_name: String(max_length=100)
    status: String(max_length=20)

@domain.query(part_of="OrderSummary")
class SearchOrders:
    status: String()
    page: Integer(default=1)
    page_size: Integer(default=20)

# Construct (validated, immutable); dispatch via a query handler
query = SearchOrders(status="placed")
result = domain.dispatch(query)  # requires a registered query handler
```

## Common mistakes

### Targeting an aggregate instead of a projection

```python
@domain.query(part_of="Order")  # Wrong! Queries target a read model
class GetOrderById:
    order_id: Identifier(required=True)
```

Instead: point `part_of` at the projection that serves the read:

```python
@domain.query(part_of="OrderSummary")  # Correct! A projection
class GetOrderById:
    order_id: Identifier(required=True)
```

### Naming a query like a command

```python
@domain.query(part_of="OrderSummary")
class FetchTheOrder:  # Vague/imperative
    order_id: Identifier(required=True)
```

Instead: name it for what it returns — `GetOrderById`, `SearchOrders`.

### Mutating a query after construction

```python
query = GetOrderById(order_id="ORD-001")
query.order_id = "ORD-002"  # Raises IncorrectUsageError!
```

Instead: create a new query instance.

### Putting associations in a query

```python
@domain.query(part_of="OrderSummary")
class SearchOrders:
    lines = HasMany("OrderLine")  # Wrong! No associations in queries
```

Instead: use basic fields (and value objects) only.

## Detailed references

- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

### Complete examples

- [Simple Query](assets/query_simple.py) - Queries against a projection
- [Query Validation](assets/query_validation.py) - Field validation and immutability

### Related skills

- `query-handler` - Answers queries via `@read` and `domain.dispatch()`
- `projection` - The read model a query targets
- `command` - The write-side counterpart (intent to change state)
- `projector` - Populates the projection that queries read from
