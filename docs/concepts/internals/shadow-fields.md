# Shadow fields

When a domain element contains a `ValueObject` or `Reference` field, Protean
creates *shadow fields*. Shadow fields are internal attributes that store
flattened data for database persistence. Shadow fields let Protean store the
rich objects you use in the domain model as flat columns in the database layer.

---

## What creates shadow fields

### ValueObject fields

Each field inside an embedded Value Object produces one shadow field on the
parent entity:

```python
--8<-- "concepts/internals/shadow-fields/001.py:value_object"
```

`Customer` gets three shadow fields:

- `billing_address_street`
- `billing_address_city`
- `billing_address_zip_code`

### Reference fields

Each `Reference` produces one shadow field, the foreign key:

```python
--8<-- "concepts/internals/shadow-fields/001.py:reference"
```

`LineItem` gets one shadow field:

- `order_id` (stores the referenced Order's identifier value)

If the target aggregate uses a custom identifier (e.g., `email` with
`identifier=True`), the shadow field name reflects it:
`order_email` instead of `order_id`.

---

## How Protean names shadow fields

| Field type | Shadow field name | Example |
|---|---|---|
| ValueObject | `{field_name}_{embedded_field_name}` | `billing_address_street` |
| Reference | `{field_name}_{target_id_field}` | `order_id` |

You can override both the ValueObject and the Reference shadow field names with
`referenced_as`, as the next section shows.

### Overriding with `referenced_as`

Use `referenced_as` on a Reference field to control the shadow field name
(i.e. the database column name):

```python
--8<-- "concepts/internals/shadow-fields/002.py:reference_referenced_as"
```

Without `referenced_as`, the shadow field would be `order_id`. With it,
the shadow field becomes `order_number`.

For ValueObject fields, apply `referenced_as` on the inner fields of the
Value Object itself:

```python
--8<-- "concepts/internals/shadow-fields/002.py:value_object_referenced_as"
```

Instead of the default `billing_address_street` and `billing_address_city`,
the shadow fields become `addr_street` and `addr_city`.

---

## Where does Protean store shadow fields?

Shadow fields are stored in the Python instance's `__dict__`, **not** as Pydantic
model fields. This means:

- `model_fields` does not include them.
- `model_dump()` does not serialize them (use `to_dict()` instead).
- `model_json_schema()` does not list them.
- `to_dict()` serializes the parent VO/Reference, not the shadow fields
  directly.

This is by design. Shadow fields are a persistence concern, not a domain model
concern. In the domain model, you access `customer.billing_address` (an
`Address` instance). The database stores `billing_address_street`,
`billing_address_city`, and `billing_address_zip_code` as separate columns.

---

## How Protean sets shadow fields

### What happens when you create an entity

When you create an entity, Protean sets its shadow fields in three stages:

**1. Protean extracts the shadow values.** Protean finds the shadow field names
in the class metadata. Protean then extracts any matching keyword arguments
from `kwargs` before Pydantic validation:

```python
--8<-- "concepts/internals/shadow-fields/001.py:extraction"
```

**2. Protean preserves the shadow values.** Protean pushes the extracted values
onto a thread-local stack (`_init_context`) because Pydantic's `__init__`
clears `__dict__` during validation.

**3. Protean restores the shadow values.** In `model_post_init()`, Protean
writes the shadow values back to `__dict__`. If a ValueObject field was not
explicitly provided, Protean reconstructs it from the shadow values:

```python
--8<-- "concepts/internals/shadow-fields/001.py:equivalent"
```

### What happens when you assign a field

When you assign to a ValueObject or Reference field, the descriptor
automatically updates the shadow fields:

```python
--8<-- "concepts/internals/shadow-fields/001.py:assignment"
```

Setting a field to `None` clears the shadow fields.

### Read and write shadow fields directly

Shadow fields can be read and written directly:

```python
--8<-- "concepts/internals/shadow-fields/001.py:direct_access"
```

---

## How database adapters persist shadow fields

Shadow fields are the mechanism that lets database adapters store
Value Objects and References as flat columns.

### How adapters generate table columns

The `attributes()` reflection function (used by database adapters) returns
shadow fields instead of the parent VO/Reference:

```python
--8<-- "concepts/internals/shadow-fields/001.py:attributes"
```

Database adapters iterate `attributes()` to generate table columns. Each
shadow field becomes a separate database column.

### Entity-to-model conversion

When persisting, the adapter reads shadow field values from `__dict__`:

```
Customer instance → {billing_address_street: "123 Main", ...} → INSERT INTO customers
```

### Model-to-entity conversion

When loading, the adapter passes shadow field values as keyword arguments:

```
SELECT * FROM customers → {billing_address_street: "123 Main", ...} → Customer(billing_address_street="123 Main", ...)
```

The entity's `model_post_init()` reconstructs the ValueObject from the
shadow values.

---

## Which serialization methods include shadow fields?

| Method | Shadow fields in output? | What appears instead |
|---|---|---|
| `to_dict()` | No | VO serialized as nested dict: `{"billing_address": {"street": "...", ...}}` |
| `model_dump()` | No | Only Pydantic model fields (avoid, use `to_dict()`) |
| Direct access | Yes | `customer.billing_address_street` returns the value |
| Database | Yes | Stored as individual columns |

If you need shadow field values in serialized output, access them directly
from the instance.
