# Shadow fields

When a domain element contains a `ValueObject` or `Reference` field, Protean
creates *shadow fields* — internal attributes that store the flattened data
needed for database persistence. Shadow fields bridge the gap between the
domain model (where you work with rich objects) and the database layer (where
data is stored in flat columns).

---

## What creates shadow fields

### ValueObject fields

Each field inside an embedded Value Object produces one shadow field on the
parent entity:

```python
class Address(BaseValueObject):
    street: String(max_length=200)
    city: String(max_length=100)
    zip_code: String(max_length=10)

@domain.aggregate
class Customer:
    name: String(max_length=100, required=True)
    billing_address: ValueObject(Address)
```

`Customer` gets three shadow fields:

- `billing_address_street`
- `billing_address_city`
- `billing_address_zip_code`

### Reference fields

Each `Reference` produces one shadow field — the foreign key:

```python
@domain.entity(part_of="Order")
class LineItem:
    description: String(max_length=200)
    order = Reference("Order")
```

`LineItem` gets one shadow field:

- `order_id` (stores the referenced Order's identifier value)

If the target aggregate uses a custom identifier (e.g., `email` with
`identifier=True`), the shadow field name reflects it:
`order_email` instead of `order_id`.

---

## Naming convention

| Field type | Shadow field name | Example |
|---|---|---|
| ValueObject | `{field_name}_{embedded_field_name}` | `billing_address_street` |
| Reference | `{field_name}_{target_id_field}` | `order_id` |

Both can be overridden with the `referenced_as` parameter on the embedded
field.

---

## Where shadow fields live

Shadow fields are stored in the Python instance's `__dict__` — **not** as
Pydantic model fields. This means:

- `model_fields` does not include them.
- `model_dump()` does not serialize them.
- `model_json_schema()` does not list them.
- `to_dict()` serializes the parent VO/Reference, not the shadow fields
  directly.

This is by design. Shadow fields are a persistence concern, not a domain
model concern. The domain model works with `customer.billing_address`
(an `Address` instance); the database works with `billing_address_street`,
`billing_address_city`, and `billing_address_zip_code` as separate columns.

---

## Lifecycle

### Initialization

When you create an entity, shadow fields are handled in three stages:

**1. Extraction.** Shadow field names are detected from the class metadata.
Any matching keyword arguments are extracted from `kwargs` before Pydantic
validation:

```python
customer = Customer(
    name="Alice",
    billing_address_street="123 Main",  # Extracted as shadow kwarg
    billing_address_city="NYC",          # Extracted as shadow kwarg
    billing_address_zip_code="10001",    # Extracted as shadow kwarg
)
```

**2. Preservation.** Extracted values are pushed onto a thread-local stack
(`_init_context`) because Pydantic's `__init__` clears `__dict__` during
validation.

**3. Restoration.** In `model_post_init()`, shadow values are written back
to `__dict__`. If a ValueObject field was not explicitly provided, Protean
reconstructs it from the shadow values:

```python
# These two are equivalent:
Customer(name="Alice", billing_address=Address(street="123 Main", city="NYC", zip_code="10001"))
Customer(name="Alice", billing_address_street="123 Main", billing_address_city="NYC", billing_address_zip_code="10001")
```

### Assignment

When you assign to a ValueObject or Reference field, the descriptor
automatically updates the shadow fields:

```python
customer.billing_address = Address(street="456 Oak", city="LA", zip_code="90001")
# Automatically sets:
#   customer.__dict__["billing_address_street"] = "456 Oak"
#   customer.__dict__["billing_address_city"] = "LA"
#   customer.__dict__["billing_address_zip_code"] = "90001"
```

Setting a field to `None` clears the shadow fields.

### Direct access

Shadow fields can be read and written directly:

```python
customer.billing_address_street  # "456 Oak"
customer.billing_address_street = "789 Pine"  # Updates shadow, marks entity as changed
```

---

## Shadow fields and persistence

Shadow fields are the mechanism that lets database adapters store
Value Objects and References as flat columns.

### Schema generation

The `attributes()` reflection function (used by database adapters) returns
shadow fields instead of the parent VO/Reference:

```python
from protean.utils.reflection import attributes

attributes(Customer)
# Returns: {
#   "name": <_FieldShim for name>,
#   "billing_address_street": <_ShadowField for street>,
#   "billing_address_city": <_ShadowField for city>,
#   "billing_address_zip_code": <_ShadowField for zip_code>,
#   "id": <_FieldShim for id>,
# }
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

## Serialization behavior

| Method | Shadow fields in output? | What appears instead |
|---|---|---|
| `to_dict()` | No | VO serialized as nested dict: `{"billing_address": {"street": "...", ...}}` |
| `model_dump()` | No | Only Pydantic model fields |
| Direct access | Yes | `customer.billing_address_street` returns the value |
| Database | Yes | Stored as individual columns |

If you need shadow field values in serialized output, access them directly
from the instance.
