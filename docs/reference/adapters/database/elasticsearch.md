# Elasticsearch

The Elasticsearch provider uses
[elasticsearch-dsl](https://elasticsearch-dsl-py.readthedocs.io/) for document
store operations, making it suitable for search and analytics workloads.

## Overview

Elasticsearch is a document-oriented provider designed for:

- **Full-text search** across domain data
- **Analytics and aggregation** workloads
- **Read-optimized views** when combined with projections

Unlike relational providers, Elasticsearch does not support real transactions
or raw queries. It is best used for read-heavy workloads where eventual
consistency is acceptable, or alongside a relational provider for write
operations.

## Installation

```bash
pip install "protean[elasticsearch]"

# Or install packages separately
pip install elasticsearch elasticsearch-dsl
```

## Configuration

```toml
[databases.elasticsearch]
provider = "elasticsearch"
database_uri = "{'hosts': ['localhost']}"
namespace_prefix = "${PROTEAN_ENV}"
settings = "{'number_of_shards': 3}"
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | Required | Must be `"elasticsearch"` for Elasticsearch |
| `database_uri` | Required | Elasticsearch connection info (hosts dict) |
| `namespace_prefix` | `None` | Prefix for index names (e.g. `prod` → `prod-person`) |
| `namespace_separator` | `"-"` | Character joining prefix and index name |
| `settings` | `None` | Index settings passed as-is to Elasticsearch |

### Namespace Prefixing

Index names are derived from aggregate class names. When `namespace_prefix` is
set, it is prepended to every index name:

| Prefix | Separator | Aggregate | Index Name |
|--------|-----------|-----------|------------|
| `prod` | `-` | `Person` | `prod-person` |
| `prod` | `_` | `Person` | `prod_person` |
| (none) | -- | `Person` | `person` |

Using `namespace_prefix = "${PROTEAN_ENV}"` lets you share a single
Elasticsearch cluster across environments by giving each environment a distinct
prefix.

## Capabilities

The Elasticsearch provider supports the following capabilities:

- :white_check_mark: **CRUD** -- Create, Read, Update, Delete single records
- :white_check_mark: **FILTER** -- Query/filter records with lookup criteria
- :white_check_mark: **BULK_OPERATIONS** -- `update_all()`, `delete_all()`
- :white_check_mark: **ORDERING** -- Server-side ordering of results
- :white_check_mark: **SCHEMA_MANAGEMENT** -- Create/drop indices
- :white_check_mark: **OPTIMISTIC_LOCKING** -- Version-based concurrency control
- :x: **TRANSACTIONS** -- No transaction support (session has no-op
  commit/rollback)
- :x: **SIMULATED_TRANSACTIONS** -- Not applicable
- :x: **RAW_QUERIES** -- Not supported
- :x: **CONNECTION_POOLING** -- Managed by the `elasticsearch` client
  internally
- :x: **NATIVE_JSON** -- Elasticsearch stores JSON natively, but this flag
  refers to SQL-style JSON columns
- :x: **NATIVE_ARRAY** -- No SQL-style array columns

## Field Mapping

Protean auto-generates an explicit Elasticsearch mapping for every
aggregate. Each Protean field type is mapped to an appropriate
`elasticsearch_dsl` field type:

| Protean Field | ES Mapping Type | Notes |
|---|---|---|
| `String` | `keyword` | Exact match, sortable, aggregatable |
| `Identifier` / `Auto` | `keyword` | Identity fields |
| `Integer` | `integer` | |
| `Float` | `float` | |
| `Boolean` | `boolean` | |
| `DateTime` | `date` | |
| `Date` | `date` | |
| `Dict` | *(dynamic)* | Uses ES dynamic mapping |
| `List` | *(dynamic)* | Uses ES dynamic mapping |
| `ValueObjectList` | `nested` | Nested objects |

String fields default to `keyword` — they support exact matching, sorting,
and aggregations out of the box. If you need full-text search with
analyzers, define a custom Elasticsearch Model (see below).

## Custom Elasticsearch Model

Supply a custom `@domain.model` when you need ES-specific field tuning
(analyzers, multi-fields, normalizers, etc.) or custom `Index` settings.
User-defined fields take precedence; unmapped attributes are filled in
automatically from the aggregate.

```python
import elasticsearch_dsl

@domain.aggregate
class Article:
    title: String()
    body: String()
    category: String()

    class Meta:
        schema_name = "articles"

@domain.model(part_of=Article)
class ArticleModel:
    # Full-text search with .keyword subfield for exact match
    title = elasticsearch_dsl.Text(
        analyzer="standard",
        fields={"keyword": elasticsearch_dsl.Keyword()}
    )
    # Full-text search only
    body = elasticsearch_dsl.Text(analyzer="english")
    # category is not listed — auto-mapped as Keyword from the aggregate

    class Index:
        settings = {"number_of_shards": 1}
```

!!! note
    When a custom model defines an `Index` inner class, its settings override
    the global `settings` from the configuration file.

!!! note
    When a custom model defines `Text`-type fields, lookups like `exact`,
    `in`, `contains`, `startswith`, and `endswith` on those fields
    automatically use the `.keyword` subfield for exact matching.

## Limitations

- **No Real Transactions** -- Elasticsearch does not support ACID transactions.
  The session object provides no-op `commit()` and `rollback()` methods. Data
  is indexed immediately on write.
- **Eventual Consistency** -- Newly indexed documents may not be immediately
  searchable. Elasticsearch refreshes indices periodically (default: 1 second).
- **No Raw Queries** -- The `raw()` method is not supported. Use the
  Elasticsearch DSL directly if you need advanced query features.
- **Requires Running Service** -- Elasticsearch must be installed and running.
  Use `make up` to start Protean's Docker-based development services.

## Next Steps

- Learn about [database capabilities](./index.md#database-capabilities) in
  detail
- Explore [PostgreSQL](./postgresql.md) for transactional workloads
- Understand the
  [ports and adapters architecture](../../../concepts/ports-and-adapters/index.md)
