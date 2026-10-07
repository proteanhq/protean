# Custom Database Models

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span>

Protean auto-generates database models for every aggregate and entity.
Custom database models let you override the default storage schema when
you need adapter-specific tuning, custom table names, Elasticsearch analyzers,
or multi-database deployments.

---

## When to use custom models

Most applications **don't need** custom models. Use them when:

- You need to override the table or collection name
- You need adapter-specific field types (e.g., Elasticsearch `Text`
  with a custom analyzer)
- You deploy one aggregate to multiple databases (e.g., PostgreSQL
  for writes + Elasticsearch for search)
- You need partial field mapping (persist only a subset of fields)

If your fields map 1:1 to standard database types, the auto-generated
model is sufficient.

---

## Defining a custom model

Subclass `BaseDatabaseModel` and register it with `part_of`:

```python
--8<-- "guides/change-state/database-models/001.py:import"
--8<-- "guides/change-state/database-models/001.py:custom_model"
```

### Overriding field types

Map aggregate fields to adapter-specific types:

```python
# fragment
from elasticsearch.dsl import Keyword, Text as ESText

class ProductSearchModel(BaseDatabaseModel):
    name = Keyword()                          # Exact match, no analysis
    description = ESText(analyzer="standard") # Full-text search

domain.register(
    ProductSearchModel,
    part_of=Product,
    database="elasticsearch",
)
```

### Partial field mapping

A model can map fewer fields than the aggregate. Unmapped fields are
handled by auto-generation:

```python
# fragment
class ProductSearchModel(BaseDatabaseModel):
    name = Keyword()  # Override only this field
    # description and price use default mapping

domain.register(ProductSearchModel, part_of=Product)
```

---

## Registration options

| Option | Type | Description |
|--------|------|-------------|
| `part_of` | class | **Required.** The aggregate or entity this model maps to |
| `schema_name` | str | Override the storage table/collection name |
| `database` | str | The database type this model applies to: `memory`, `sqlite`, `postgresql`, `mysql`, `mssql` or `elasticsearch`. This is not a provider name. Without it, the model is used for any database type that has no model of its own. |

```python
class ProductReportingModel(BaseDatabaseModel):
    pass


domain.register(
    ProductReportingModel,
    part_of=Product,
    schema_name="product_reports",
    database="postgresql",
)
```

---

## Multi-database deployment

Register multiple models for the same aggregate, each targeting a
different database type:

```python
# fragment
class CustomerWriteModel(BaseDatabaseModel):
    pass

class CustomerSearchModel(BaseDatabaseModel):
    name = Keyword()

domain.register(
    CustomerWriteModel,
    part_of=Customer,
    database="postgresql",
    schema_name="customers",
)
domain.register(
    CustomerSearchModel,
    part_of=Customer,
    database="elasticsearch",
    schema_name="customer_index",
)
```

---

## Validation rules

- Model fields **must be a subset** of the aggregate's fields. Defining
  a field that doesn't exist on the aggregate raises `IncorrectUsageError`.
- A model can have fewer fields than the aggregate (partial mapping).
- A model cannot add fields not present on the aggregate.

---

!!! tip "See also"
    - [Adapters Reference](../../reference/adapters/index.md): Provider-specific
      configuration and field types.
    - [Custom Databases](../../reference/adapters/database/custom-databases.md):
      Building your own database adapter.
