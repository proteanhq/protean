# Custom Database Models

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span>

Protean auto-generates database models for every aggregate and entity.
Custom database models let you override the default storage schema when
you need adapter-specific tuning, custom table names, Elasticsearch analyzers,
or a different model for each database type.

---

## When to use custom models

Most applications **don't need** custom models. Use them when:

- You need to override the table or collection name
- You need adapter-specific field types (e.g., Elasticsearch `Text`
  with a custom analyzer)
- One aggregate runs on different database types in different deployments
  (e.g., PostgreSQL in one, Elasticsearch in another), and each needs its
  own model
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
--8<-- "guides/change-state/database-models/002.py:field_types"
```

### Partial field mapping

A model can map fewer fields than the aggregate. Unmapped fields are
handled by auto-generation:

```python
--8<-- "guides/change-state/database-models/003.py:partial"
```

---

## Registration options

| Option | Type | Description |
|--------|------|-------------|
| `part_of` | class | **Required.** The aggregate or entity this model maps to |
| `schema_name` | str | Override the storage table/collection name |
| `database` | str | The database type this model applies to: `memory`, `sqlite`, `postgresql`, `mysql`, `mssql` or `elasticsearch`. This is not a provider name. It has no default: without it, the model is used for any database type that has no model of its own. |

```python
--8<-- "guides/change-state/database-models/001.py:options"
```

---

## Multi-database deployment

Register multiple models for the same aggregate, each targeting a
different database type:

```python
--8<-- "guides/change-state/database-models/004.py:multi_database"
```

An aggregate is stored in one provider, set with its `provider` option. Its
repository uses the model whose `database` matches that provider's database
type, so `Customer` above uses `CustomerSearchModel` on Elasticsearch and
`CustomerWriteModel` on PostgreSQL. The aggregate is not written to both.

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
