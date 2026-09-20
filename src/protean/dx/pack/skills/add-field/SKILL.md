---
name: add-field
description: Add fields to Protean domain elements (aggregates, entities, value objects). Guides you through selecting the right field type, configuring validations, and placing fields correctly. Use when the user asks to "add a field", "add an attribute", "add a property", "I need to store [data]", "add a new field to [aggregate/entity]", or describes data that needs to be tracked. Covers simple fields, association fields (HasOne, HasMany, ValueObject), field validation, custom validators, and choosing between field types for different use cases.
license: Apache-2.0
compatibility: "Requires Python 3.11+, protean framework"
metadata:
  author: proteanhq
  version: "0.1"
  category: workflow
  composes: [aggregate, entity, value-object]
---

# Add Field

Guide for adding fields to Protean domain elements — choosing the right type, configuring
parameters, and placing fields correctly.

## Information to gather

Before adding a field:

- [ ] **Target element** — Which aggregate, entity, or value object?
- [ ] **Data purpose** — What does this field represent?
- [ ] **Data type** — Text, number, date, boolean, relationship?
- [ ] **Required or optional?**
- [ ] **Default value?**
- [ ] **Validation rules?** — Length, range, format, cross-field?
- [ ] **Relationship?** — Is this a reference to another domain element?

## Process

### Step 1: Choose where the field goes

| Target | When | Patterns |
|--------|------|----------|
| **Aggregate** | Root domain object | See [aggregate](../aggregate/SKILL.md) |
| **Entity** | Child object within an aggregate (has identity) | See [entity](../entity/SKILL.md) — always needs `part_of="AggName"` |
| **Value Object** | Immutable descriptive concept (no identity) | See [value-object](../value-object/SKILL.md) |

### Step 2: Choose the field type

#### Decision: Simple field vs ValueObject

**Use a simple field** when the data is a single value with no behavior:

```python
email = String(required=True, max_length=254)
price = Float(required=True, min_value=0.01)
```

**Use ValueObject** when the data has multiple related attributes, behavior, or should
be reusable:

```python
total = ValueObject(Money)       # Money has amount + currency + add()/multiply()
address = ValueObject(Address)   # Address has street + city + state + zip + format()
```

**Rule of thumb**: If you see two fields that always travel together (amount + currency,
street + city), extract a value object. See [refactor-extract-value-object](../refactor-extract-value-object/SKILL.md).

#### Decision: HasMany vs List

**Use HasMany** for entities with identity and behavior:

```python
line_items = HasMany("LineItem")  # LineItem is an entity with its own identity
```

**Use List** for simple values without identity:

```python
tags = List(content_type=String)  # Just strings, no identity
```

#### Quick field type reference

| Data | Field type | Example |
|------|-----------|---------|
| Short text | `String(max_length=N)` | names, codes, statuses |
| Long text | `Text()` | descriptions, notes |
| Whole number | `Integer()` | counts, quantities |
| Decimal | `Float()` | prices, percentages |
| True/False | `Boolean(default=True)` | flags |
| Date only | `Date()` | birth_date, expiry_date |
| Date + time | `DateTime()` | timestamps |
| Identity | `String(identifier=True)` | custom IDs |
| One child entity | `HasOne("Entity")` | one-to-one |
| Many child entities | `HasMany("Entity")` | one-to-many |
| Embedded VO | `ValueObject(VOClass)` | Money, Address |
| Reference to aggregate | `Reference("OtherAgg")` | foreign key |
| Simple list | `List(content_type=String)` | tags, codes |
| Key-value | `Dict()` | metadata |

### Step 3: Configure field parameters

```python
# Required vs optional
name = String(required=True)
description = String()              # Optional (can be None)

# Defaults
status = String(default="draft")

# Constraints
sku = String(unique=True, max_length=50)
price = Float(min_value=0.01, max_value=999999.99)
quantity = Integer(min_value=1, max_value=10000)

# Enum-like choices
status = String(choices=["draft", "published", "archived"])

# Custom validators
email = String(validators=[EmailValidator()])
```

### Step 4: Choose validation layer

| Rule type | Where | How |
|-----------|-------|-----|
| Single-field constraint | Field parameter | `Float(min_value=0.01)` |
| Format validation | Custom validator | `String(validators=[EmailValidator()])` |
| Cross-field business rule | `@invariant.post` on aggregate | See [add-validation](../add-validation/SKILL.md) |
| State-dependent guard | Method body | `if self.status != "DRAFT": raise ...` |

**Never duplicate**: if a rule can be expressed as a field parameter, don't also add an invariant.

## HasMany auto-generated methods

When you add `items = HasMany("LineItem")`, these methods are automatically available:

- `aggregate.add_items(item)` — Add one or more items
- `aggregate.remove_items(item)` — Remove an item
- `aggregate.get_one_from_items(id)` — Get by identifier
- `aggregate.filter_items(**criteria)` — Filter items

**Never manually define these methods** — they exist automatically.

## Common mistakes

- **Primitives instead of value objects** — `total_amount` + `total_currency` should be `ValueObject(Money)`
- **Wrong field type** — Use `Integer`/`Float` for numbers, not `String`. Use `Date`/`DateTime` for dates.
- **Forgetting `part_of` on entities** — Always specify `@domain.entity(part_of="Order")`
- **Recreating HasMany helpers** — Don't define `add_items()` manually
- **Field validation AND invariant** — Pick one layer, don't duplicate

See [references/common-mistakes.md](references/common-mistakes.md) for detailed examples.

## Complete examples

- [Simple fields](assets/add_simple_field.py) — Adding basic fields to an aggregate
- [Custom validator](assets/add_field_with_custom_validator.py) — Field with custom validation
- [Association fields](assets/add_association_fields.py) — HasOne, HasMany, Reference
- [ValueObject field](assets/add_value_object_field.py) — Embedding a value object

## Detailed references

- [Field Types Guide](references/field-types.md) — Comprehensive guide to all field types
- [Validation Strategies](references/validation.md) — Field validation vs invariants
- [Association Fields](references/associations.md) — HasOne, HasMany, ValueObject, Reference
- [Common Mistakes](references/common-mistakes.md) — Anti-patterns when adding fields

## Related skills

- [aggregate](../aggregate/SKILL.md) — Aggregate field patterns
- [entity](../entity/SKILL.md) — Entity field patterns
- [value-object](../value-object/SKILL.md) — Value object definition
- [add-validation](../add-validation/SKILL.md) — Choosing the right validation layer
- [custom-validator](../custom-validator/SKILL.md) — Building custom field validators
- [refactor-extract-value-object](../refactor-extract-value-object/SKILL.md) — When fields should become VOs
