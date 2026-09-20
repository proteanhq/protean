---
name: refactor-extract-value-object
description: >
  Extract value objects from primitive fields in Protean aggregates, entities, and commands.
  Detects primitive obsession — raw String/Float/Integer fields representing domain concepts
  that deserve their own type — and refactors them into proper value objects. Use when the user
  says "extract value object", "create a value object from these fields", "fix primitive obsession",
  "these fields should be a VO", "refactor money fields", "extract address", or when an audit
  identifies primitive obsession as a code smell.
license: Apache-2.0
compatibility: "Requires Python 3.11+, protean framework"
metadata:
  author: proteanhq
  version: "0.1"
  category: workflow
  composes: [value-object, aggregate, entity]
---

# Refactor: Extract Value Object

> **Illustrative, guided refactoring.** This is a before→after walkthrough, not an
> automated transform: recognize the smell and apply the change yourself, adapting to the
> code at hand. The `extract_vo_*_before.py` assets are the intentional starting point
> (primitive obsession); the `*_after.py` assets show the target.

Identify primitive field groups or single fields representing domain concepts, extract them
into value objects, and update all references.

## What this produces

| Output | Purpose |
|--------|---------|
| **New value object class** | `@domain.value_object` with fields and optional behavior |
| **Updated aggregate/entity** | `ValueObject(NewVO)` replacing primitive fields |
| **Updated commands/events** | Fields aligned with new VO structure |
| **Updated tests** | Tests for the new VO and updated aggregate tests |

## Detection patterns

### Multi-field groups (strongest signal)

Fields that always travel together are a VO waiting to be extracted:

| Field pattern | Extract to |
|--------------|------------|
| `amount` + `currency` | `Money` |
| `street` + `city` + `state` + `zip_code` + `country` | `Address` |
| `latitude` + `longitude` | `Coordinates` |
| `first_name` + `last_name` | `PersonName` |
| `start_date` + `end_date` | `DateRange` |
| `quantity` + `unit` | `Measurement` |
| `width` + `height` + `depth` | `Dimensions` |
| `area_code` + `number` + `extension` | `PhoneNumber` |

### Single fields with implicit concepts

A single field that carries domain meaning beyond its raw type:

| Field pattern | Extract to |
|--------------|------------|
| `email = String(...)` | `Email` (with format validation) |
| `phone = String(...)` | `PhoneNumber` (with format validation) |
| `price = Float(...)` | `Money` (with currency) |
| `url = String(...)` | `Url` (with format validation) |
| `sku = String(...)` | `SKU` (with format rules) |
| `percentage = Float(...)` | `Percentage` (with 0-100 constraint) |

### Cross-aggregate repetition

The same field group appearing in 2+ aggregates is the strongest signal — extract once, use everywhere.

## Process

### Step 1: Identify candidates

Scan aggregate and entity definitions for the patterns above. For each candidate, note:
- **Which fields** to extract
- **Which aggregates/entities** use them
- **What behavior** the fields participate in (calculations, comparisons, formatting)

### Step 2: Design the value object

Follow [value-object](../value-object/SKILL.md) patterns:

```python
@domain.value_object
class Money:
    amount = Float(required=True)
    currency = String(max_length=3, default="USD")

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError(f"Cannot add {self.currency} and {other.currency}")
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def multiply(self, factor: int) -> "Money":
        return Money(amount=self.amount * factor, currency=self.currency)
```

Key decisions:
1. **Fields**: Move from the aggregate — keep the same types and constraints
2. **Behavior**: Extract related calculations and comparisons from handlers/aggregates
3. **Invariants**: Add `@invariant.post` for concept-level validation
4. **Immutability**: VOs are automatically immutable — no setters needed

### Step 3: Replace primitive fields

In each aggregate/entity, replace the field group with a `ValueObject` field:

```python
# Before
@domain.aggregate
class Order:
    total_amount = Float(default=0.0)
    total_currency = String(default="USD")

# After
@domain.aggregate
class Order:
    total = ValueObject(Money)
```

### Step 4: Update aggregate methods

Replace inline calculations with VO methods:

```python
# Before
def apply_discount(self, percentage):
    self.total_amount = self.total_amount * (1 - percentage / 100)

# After
def apply_discount(self, percentage):
    discount = self.total.multiply_by_fraction(1 - percentage / 100)
    self.total = discount
```

### Step 5: Update commands and events

Decide: flatten or nest?

```python
# Option A: Flatten (simpler for API consumers)
@domain.command(part_of="Order")
class PlaceOrder:
    amount = Float(required=True)
    currency = String(default="USD")

# Option B: Nest (preserves VO semantics)
@domain.command(part_of="Order")
class PlaceOrder:
    total = ValueObject(Money, required=True)
```

For events, flattening is often preferred since events are read by many consumers.

### Step 6: Update tests

1. Add tests for the new VO (construction, behavior, invariants)
2. Update aggregate tests to use VO construction
3. Update assertion patterns:
   ```python
   # Before
   assert order.total_amount == 59.98
   assert order.total_currency == "USD"

   # After
   assert order.total.amount == 59.98
   assert order.total.currency == "USD"
   ```

## Common mistakes

1. **Extracting without behavior** — A VO with only fields and no methods is often premature.
   Ask: does this concept have operations (add, compare, format)?

2. **Over-extracting** — Not every pair of fields is a VO. `created_at` + `updated_at` are
   independent timestamps, not a "TimeRange".

3. **Breaking event schemas** — If events are persisted (event store), changing field structure
   is a schema change. Add `__version__` bump and an upcaster.

4. **Forgetting HasMany entities** — If the primitive fields are on entities inside a `HasMany`,
   update those too.

5. **Losing default values** — When moving `default=0.0` from the aggregate to the VO,
   make sure the VO field or the aggregate `ValueObject()` field carries the default.

## Quick example

```python
# Before: primitive obsession
@domain.aggregate
class Invoice:
    subtotal_amount = Float(default=0.0)
    subtotal_currency = String(default="USD")
    tax_amount = Float(default=0.0)
    tax_currency = String(default="USD")

# After: value objects
@domain.value_object
class Money:
    amount = Float(required=True)
    currency = String(max_length=3, default="USD")

    def add(self, other: "Money") -> "Money":
        return Money(amount=self.amount + other.amount, currency=self.currency)

@domain.aggregate
class Invoice:
    subtotal = ValueObject(Money)
    tax = ValueObject(Money)

    @property
    def total(self) -> Money:
        return self.subtotal.add(self.tax) if self.subtotal and self.tax else None
```

## Examples

- Address: [before](assets/extract_vo_address_before.py) and [after](assets/extract_vo_address_after.py)
- Money: [before](assets/extract_vo_money_before.py) and [after](assets/extract_vo_money_after.py)

## Detailed references

- [Common value objects](references/common-value-objects.md) — Catalog of common VOs with implementations
- [Migration guide](references/migration-guide.md) — Step-by-step for migrating existing data
- [Anti-patterns](references/anti-patterns.md) — Extraction pitfalls

## Related skills

- [value-object](../value-object/SKILL.md) — Full VO patterns and rules
- [audit-domain](../audit-domain/SKILL.md) — Detects primitive obsession
- [aggregate](../aggregate/SKILL.md) — Aggregate patterns including VO usage

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
