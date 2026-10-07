# Elasticsearch

The Elasticsearch provider uses the
[DSL module](https://elasticsearch-py.readthedocs.io/en/stable/dsl.html) that
ships with the `elasticsearch` client (`elasticsearch.dsl`) for document store
operations, making it suitable for search and analytics workloads.

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

# Or install the client separately
pip install "elasticsearch>=8.18.0,<9.0.0"
```

## Configuration

```toml
--8<-- "adapters/database/elasticsearch/domain.toml"
```

Aggregates declared with `provider="search"` are stored in Elasticsearch.
`${ELASTICSEARCH_HOST|...}` reads the host from the `ELASTICSEARCH_HOST`
environment variable, and uses the value after `|` when it is not set.

The provider reads `NAMESPACE_PREFIX`, `NAMESPACE_SEPARATOR` and `SETTINGS` in
upper case only. In lower case they are ignored.

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | Required | Must be `"elasticsearch"` for Elasticsearch |
| `database_uri` | Required | A table with a `hosts` list. Each host is a `scheme://host:port` URL, or `host:port` (the scheme is then `http`) |
| `NAMESPACE_PREFIX` | `None` | Prefix for index names (e.g. `prod` → `prod_person`) |
| `NAMESPACE_SEPARATOR` | `"_"` | Character joining prefix and index name |
| `SETTINGS` | `None` | Index settings passed as-is to Elasticsearch |

### Namespace Prefixing

Index names are derived from aggregate class names. When `NAMESPACE_PREFIX` is
set, it is prepended to every index name:

| Prefix | Separator | Aggregate | Index Name |
|--------|-----------|-----------|------------|
| `prod` | `_` (default) | `Person` | `prod_person` |
| `prod` | `-` | `Person` | `prod-person` |
| (none) | —  | `Person` | `person` |

Using `NAMESPACE_PREFIX = "${PROTEAN_ENV}"` lets you share a single
Elasticsearch cluster across environments by giving each environment a distinct
prefix.

## Capabilities

The Elasticsearch provider supports the following capabilities:

- :white_check_mark: **CRUD**: Create, Read, Update, Delete single records
- :white_check_mark: **FILTER**: Query/filter records with lookup criteria
- :white_check_mark: **BULK_OPERATIONS**: `update_all()`, `delete_all()`
- :white_check_mark: **ORDERING**: Server-side ordering of results
- :white_check_mark: **SCHEMA_MANAGEMENT**: Create/drop indices
- :white_check_mark: **OPTIMISTIC_LOCKING**: Version-based concurrency control
- :x: **TRANSACTIONS**: No transaction support (session has no-op
  commit/rollback)
- :x: **SIMULATED_TRANSACTIONS**: Not applicable
- :x: **RAW_QUERIES**: Not supported
- :x: **CONNECTION_POOLING**: Managed by the `elasticsearch` client
  internally
- :x: **NATIVE_JSON**: Elasticsearch stores JSON natively, but this flag
  refers to SQL-style JSON columns
- :x: **NATIVE_ARRAY**: No SQL-style array columns

## Indexes

Elasticsearch does not use relational indexes, so portable
[`Index`](../../domain-elements/indexes.md) declarations are not translated into
DDL here. Configure search behavior through the Elasticsearch field mapping
(below) instead. Index declarations on an aggregate remain valid (they are
honored by SQL providers); they are not applied by this adapter.

## Field Mapping

Protean auto-generates an explicit Elasticsearch mapping for every
aggregate. Each Protean field type is mapped to an appropriate
`elasticsearch.dsl` field type:

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

String fields default to `keyword`. They support exact matching, sorting, and
aggregations. If you need full-text search with analyzers, define a custom
Elasticsearch Model (see below).

## Custom Elasticsearch Model

Supply a custom `@domain.database_model` when you need ES-specific field tuning
(analyzers, multi-fields, normalizers, etc.). User-defined fields take
precedence; unmapped attributes are filled in automatically from the aggregate.
This example needs a running Elasticsearch server:

```python
# fragment
--8<-- "adapters/database/elasticsearch/001.py:full"
```

The index is named `articles`, from the aggregate's `schema_name` option.
`title` and `body` are mapped as `text`, and `category` as `keyword`.

!!! note
    Index settings come from the `SETTINGS` configuration option. For a
    custom model written as a plain class, as above, Protean builds the
    model's `Index` inner class itself, so `settings` declared on that class
    are not used. A custom model that already subclasses Protean's
    `ElasticsearchModel` keeps its own `Index` class.

!!! note
    When a custom model defines `Text`-type fields, lookups like `exact`,
    `in`, `contains`, `startswith`, and `endswith` on those fields
    automatically use the `.keyword` subfield for exact matching.

## Limitations

- **No Real Transactions**: Elasticsearch does not support ACID transactions.
  The session object provides no-op `commit()` and `rollback()` methods. Data
  is indexed immediately on write.
- **Eventual Consistency**: Newly indexed documents may not be immediately
  searchable. Elasticsearch refreshes indices periodically (default: 1 second).
- **No Raw Queries**: The `raw()` method is not supported. Use the
  Elasticsearch DSL directly if you need advanced query features.
- **Requires Running Service**: Elasticsearch must be installed and running.
  Use `make up` to start Protean's Docker-based development services.

## Related pages

- Learn about [database capabilities](./index.md#database-capabilities) in
  detail
- Explore [PostgreSQL](./postgresql.md) for transactional workloads
- Understand the
  [ports and adapters architecture](../../../concepts/ports-and-adapters/index.md)
