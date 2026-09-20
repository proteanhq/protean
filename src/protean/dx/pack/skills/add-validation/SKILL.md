---
name: add-validation
description: Implement validation in Protean domain elements at the correct layer. Protean has 4 validation layers - Layer 1 (field constraints like required, max_length, min_value, choices), Layer 2 (value object invariants via @invariant.post for concept-level rules), Layer 3 (aggregate invariants via @invariant.pre and @invariant.post for business rules and state guards), Layer 4 (handler/service guards for authorization and context-dependent checks). Use when the user asks to "add validation", "add a business rule", "enforce a constraint", "add an invariant", "validate input", "add a guard", "implement a business rule", "add a pre-condition", "add a post-condition", or when they describe rules like "ensure X cannot be negative", "X must be before Y", "only active users can do X", or "total must equal sum of items".
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: workflow
  composes: [aggregate, value-object, entity, command-handler, custom-validator]
---

# Add Validation

Protean organizes validation into 4 distinct layers. Each layer has a specific purpose and mechanism. Choosing the right layer ensures validations run at the correct time, provide clear error messages, and don't duplicate logic.

## The 4 validation layers

| Layer | Mechanism | Purpose | When it runs |
|-------|-----------|---------|-------------|
| **1. Field constraints** | Field parameters | Type safety, format, range, presence | On field assignment |
| **2. Value object invariants** | `@invariant.post` | Domain concept rules | After VO creation |
| **3. Aggregate invariants** | `@invariant.pre` / `@invariant.post` | Business rules, cross-field consistency | Before/after state changes |
| **4. Handler/service guards** | Explicit checks in handler | Authorization, context-dependent rules | During command processing |

## Information to gather

Before adding a validation, understand:

- [ ] **What is the rule?** — State it as a business constraint (e.g., "discount cannot exceed order total")
- [ ] **How many fields does it involve?** — Single-field → Layer 1 or 2; Cross-field → Layer 3; Context-dependent → Layer 4
- [ ] **Where does it belong?** — Which aggregate, entity, value object, or handler?
- [ ] **When should it run?** — Always (Layer 1-3) or only during specific operations (Layer 4)?
- [ ] **Is it a pre-condition or post-condition?** — Before change (`@invariant.pre`) or after change (`@invariant.post`)?

## Layer 1: Field constraints

Use for single-field data type rules. These are the simplest and most common validations.

```python
from protean.fields import String, Integer, Float, Date
from enum import Enum

class OrderStatus(Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    SHIPPED = "SHIPPED"

@domain.aggregate
class Order:
    # Required field
    customer_id: String(required=True)

    # Range constraints
    quantity: Integer(required=True, min_value=1, max_value=10000)
    price: Float(required=True, min_value=0.01)

    # Length constraints
    notes: String(max_length=500)

    # Enum/choices constraint
    status: String(max_length=10, choices=OrderStatus, default="DRAFT")
```

**When to use Layer 1**:
- `required=True` — Field must have a value
- `min_value` / `max_value` — Numeric range
- `min_length` / `max_length` — String length
- `choices` — Value must be from enum/list
- `validators=[...]` — Custom single-field format checks (see [custom-validator](../custom-validator/SKILL.md))

**Validation timing**: Immediately on field assignment (during `__init__` or `__setattr__`).

## Layer 2: Value object invariants

Use for domain concept rules that span multiple fields of a value object. Value objects only support `@invariant.post` (they are immutable — no pre-conditions).

```python
from protean import invariant
from protean.exceptions import ValidationError

@domain.value_object
class DateRange:
    start_date: Date(required=True)
    end_date: Date(required=True)

    @invariant.post
    def end_must_be_after_start(self):
        """End date must be after start date."""
        if self.end_date <= self.start_date:
            raise ValidationError(
                {"date_range": ["End date must be after start date"]}
            )

@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, required=True)

    @invariant.post
    def amount_must_be_non_negative(self):
        """Money amounts cannot be negative."""
        if self.amount < 0:
            raise ValidationError(
                {"amount": ["Amount cannot be negative"]}
            )
```

**When to use Layer 2**:
- Cross-field rules within a value object (end > start, amount matches currency rules)
- Domain concept validation (valid ISO currency, valid coordinate ranges)
- Rules that are inherent to the concept itself, not specific to any aggregate

**Validation timing**: After all fields are set during VO initialization.

## Layer 3: Aggregate invariants

Use for business rules that enforce consistency across an aggregate's state. Supports both `@invariant.pre` (before change) and `@invariant.post` (after change).

```python
@domain.aggregate
class Order:
    status: String(default="draft")
    items = HasMany("LineItem")
    total_amount: Float(default=0.0)

    @invariant.post
    def total_must_equal_sum_of_items(self):
        """Order total must match sum of line item subtotals."""
        expected = sum(item.subtotal for item in self.items)
        if self.total_amount != expected:
            raise ValidationError(
                {"_entity": ["Total must equal sum of item subtotals"]}
            )

    @invariant.post
    def must_have_items_when_placed(self):
        """Placed orders must have at least one item."""
        if self.status != "draft" and not self.items:
            raise ValidationError(
                {"items": ["Order must have at least one item when placed"]}
            )

    @invariant.pre
    def cannot_modify_shipped_order(self):
        """Shipped orders cannot be modified."""
        if self.status == "shipped":
            raise ValidationError(
                {"_entity": ["Cannot modify a shipped order"]}
            )
```

**`@invariant.pre` vs `@invariant.post`**:
- **`@invariant.pre`** — Checked BEFORE attribute changes (not on initialization). Use for state guards: "cannot modify shipped orders", "cannot withdraw below limit".
- **`@invariant.post`** — Checked AFTER initialization AND after each attribute change. Use for consistency rules: "total must equal sum", "must have items when placed".

**When to use Layer 3**:
- Cross-field business rules within an aggregate
- State machine guards (pre-conditions on transitions)
- Collection constraints (minimum items, totals must match)
- Rules that depend on the aggregate's current state

**Validation timing**: Pre-invariants before attribute changes; post-invariants after initialization and attribute changes.

### Atomic changes

When multiple attributes need to change together, use `atomic_change` to defer validation until all changes are made:

```python
from protean import atomic_change

with atomic_change(order):
    order.total_amount = 120.0  # No validation yet
    order.add_items(
        LineItem(product_id="P3", quantity=2, price=10.0, subtotal=20.0)
    )
# Post-invariants checked here — aggregate is now valid
```

## Layer 4: Handler/service guards

Use for authorization, context-dependent rules, and checks that need external data not available inside the aggregate.

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler:

    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        # Layer 4: Context-dependent guard
        if command.requested_by_role not in ["customer", "admin"]:
            raise ValidationError(
                {"authorization": ["Only customers or admins can place orders"]}
            )

        # Layer 4: External data check
        order = domain.repository_for(Order).get(command.order_id)
        if order is None:
            raise ValidationError(
                {"order_id": [f"Order {command.order_id} not found"]}
            )

        # Business logic (Layers 1-3 validate automatically)
        order.place()
        domain.repository_for(Order).add(order)
```

**When to use Layer 4**:
- Authorization checks (role-based, permission-based)
- Existence checks (does the referenced entity exist?)
- Cross-aggregate consistency (check another aggregate's state)
- Rate limiting, quota checks
- Any rule that needs data not available inside the aggregate

**Validation timing**: During handler execution, before aggregate operations.

## Decision guide: Choosing the right layer

```
Is it a single-field data constraint?
├── Yes → Layer 1 (field parameters)
│   Examples: required, max_length, min_value, choices, validators=[]
│
└── No → Does it involve multiple fields?
    ├── Within a value object → Layer 2 (VO @invariant.post)
    │   Examples: end > start, amount >= 0 for currency
    │
    ├── Within an aggregate/entity → Layer 3 (aggregate invariants)
    │   │
    │   ├── Before change guard? → @invariant.pre
    │   │   Examples: cannot modify shipped, check balance before debit
    │   │
    │   └── After change consistency? → @invariant.post
    │       Examples: total = sum(items), must have items when placed
    │
    └── Needs external data or context? → Layer 4 (handler guard)
        Examples: authorization, existence checks, cross-aggregate rules
```

## Key rules

1. **Start at Layer 1** — Use field parameters whenever possible. They're the simplest, fastest, and auto-documented.
2. **Prefer invariants over manual checks** — Use `@invariant.pre`/`@invariant.post` instead of `if` checks in methods. Invariants run automatically.
3. **One rule per invariant** — Keep invariants granular. One business rule per decorated method.
4. **Use descriptive invariant names** — Name invariants as business rules: `total_must_equal_sum_of_items`, not `validate_total`.
5. **Raise `ValidationError` with field context** — Use `{"field_name": ["message"]}` format. Use `"_entity"` key for aggregate-level rules.
6. **Don't duplicate across layers** — If `Float(min_value=0)` handles it, don't also add an invariant for the same check.
7. **Pre-invariants don't run on initialization** — `@invariant.pre` only runs before attribute changes AFTER the object is created.

## Common mistakes

- **Putting business rules in handlers** — Business rules belong in aggregates (Layer 3), not handlers. Handlers are for authorization and orchestration.
- **Duplicating field constraints as invariants** — If `Integer(min_value=1)` enforces "quantity >= 1", don't also write an invariant for it.
- **Using `@invariant.pre` on value objects** — Value objects are immutable; only `@invariant.post` applies.
- **Not using `atomic_change` for multi-field updates** — When changing related fields together, wrap in `atomic_change` to avoid intermediate invalid states.
- **Putting all validation in `__init__`** — Use Protean's validation framework (fields + invariants), not manual `__init__` checks.

## Complete examples

- [Layer 1: Field constraints](assets/validation_layer1_field_constraints.py)
- [Layer 2: Value object invariants](assets/validation_layer2_vo_invariants.py)
- [Layer 3: Aggregate invariants](assets/validation_layer3_aggregate_invariants.py)
- [Layer 4: Handler guards](assets/validation_layer4_handler_guards.py)
- [All layers combined](assets/validation_all_layers.py)

## Detailed references

- [Layer 1: Field Constraints](references/layer1-field-constraints.md) - All field validation parameters
- [Layer 2: Value Object Invariants](references/layer2-value-object-invariants.md) - VO invariant patterns
- [Layer 3: Aggregate Invariants](references/layer3-aggregate-invariants.md) - Pre/post invariants and atomic changes
- [Layer 4: Handler Guards](references/layer4-handler-guards.md) - Authorization and context checks
- [Choosing the Right Layer](references/choosing-the-right-layer.md) - Decision framework with examples

## Related skills

- [custom-validator](../custom-validator/SKILL.md) - Build custom field validators (Layer 1 extension)
- [aggregate](../aggregate/SKILL.md) - Aggregates with invariants
- [value-object](../value-object/SKILL.md) - Value objects with invariants
- [entity](../entity/SKILL.md) - Entities within aggregates
- [command-handler](../command-handler/SKILL.md) - Handler guards (Layer 4)
- [add-field](../add-field/SKILL.md) - Adding fields with validation

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
