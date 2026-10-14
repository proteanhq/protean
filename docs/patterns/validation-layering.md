# Validation Layering

## The Problem

A developer adds email validation to a `User` aggregate:

```python
--8<-- "patterns/validation-layering/001.py:user"
```

Two validations, both on the aggregate's invariants, but they serve different
purposes. The email format check is a universal truth about email addresses. It
applies regardless of context. The admin-company-email rule is a business
policy that could change, applies only to admins, and depends on the
aggregate's role field.

Mixing these creates problems:

- **Wrong error granularity**: A user entering `"bad-email"` gets a format
  error at the aggregate level, after the command is already processed. The
  error could have been caught earlier, at the field or value object level,
  with a clearer message.

- **Duplicated validation**: If `Email` is used in multiple aggregates
  (`User`, `Contact`, `Newsletter`), the format check is duplicated in each.
  If the format rule changes (e.g., accepting `+` in local parts), every
  aggregate must be updated.

- **Authorization mixed with domain rules**: "Only admins can cancel orders"
  is an authorization check, not a domain invariant. Putting it in the
  aggregate mixes infrastructure concerns with domain logic.

- **Validation at the wrong time**: A command with clearly invalid data
  (missing required fields, wrong types) travels through the system, gets
  deserialized, processed by a handler, applied to an aggregate, all before the
  aggregate's invariant catches the error. The error surface is broad and the
  feedback is delayed.

The root cause: **all validation is treated the same, regardless of its nature,
urgency, or scope**.

---

## The Pattern

Organize validation into **layers**, each with a specific purpose, scope, and
position in the processing pipeline. Each layer catches a different category
of invalid state.

```
Layer 1: Field Constraints        (Type safety, format, range)
    ↓
Layer 2: Value Object Invariants  (Domain concept rules)
    ↓
Layer 3: Aggregate Invariants     (Business rules, cross-field consistency)
    ↓
Layer 4: Handler/Service Guards   (Contextual rules, authorization, state checks)
```

Each layer catches errors earlier and more specifically than the next. Errors
that slip through one layer are caught by the next.

---

## Layer 1: Field Constraints

**What it validates:** Data types, formats, ranges, required-ness, and
choices at the individual field level.

**Where it lives:** Field declarations on aggregates, entities, value objects,
commands, and events.

**When it runs:** At object construction, when a value is assigned to a field.

```python
--8<-- "patterns/validation-layering/002.py:product"
```

**What this catches:**

- `name=None` when `required=True` → Validation error
- `name="x" * 201` when `max_length=200` → Validation error
- `price=-5.0` when `min_value=0.0` → Validation error
- `status="invalid"` when `choices=[...]` → Validation error
- `stock_count="abc"` when type is `Integer` → Type conversion error

**What this should NOT catch:**

- Business rules ("price must be higher than cost"), that's Layer 3
- Cross-field validation ("if status is active, stock must be > 0"), Layer 3
- Format patterns specific to domain concepts ("SKU must match XX-NNNN"),
  Layer 2

Field constraints are the first defense. They're declarative, visible in the
field definition, and enforced automatically by Protean.

---

## Layer 2: Value Object Invariants

**What it validates:** Rules intrinsic to a domain concept, format patterns,
internal consistency, and constraints that define what makes a concept valid.

**Where it lives:** Invariants on value objects.

**When it runs:** At value object construction (which triggers during aggregate
construction or field assignment).

```python
--8<-- "patterns/validation-layering/003.py:value_objects"
```

**What this catches:**

- `Email(address="not-an-email")` → Invalid format
- `Money(amount=-5, currency="USD")` → Negative amount
- `Money(amount=10, currency="XYZ")` → Invalid currency
- `DateRange(start_date=today, end_date=yesterday)` → End before start

**What this should NOT catch:**

- Business rules about how the value is used in context ("Money amount must
  not exceed the account's credit limit"), that's Layer 3
- Whether the current user is allowed to set this value, that's Layer 4

Value object invariants are **context-free**. An `Email` is either valid or
not, regardless of which aggregate it's in or who is setting it.

---

## Layer 3: Aggregate Invariants

**What it validates:** Business rules that depend on the aggregate's state,
cross-field consistency, state machine rules, and domain-specific constraints.

**Where it lives:** Invariants on aggregates and entities.

**When it runs:** After aggregate methods are called (post-invariants) or
before specific operations (pre-invariants).

```python
--8<-- "patterns/validation-layering/003.py:aggregate"
```

**What this catches:**

- Placing an order with no items (cross-field: status + items)
- Discount exceeding total (cross-field: discount + total)
- Total mismatch with item sum (cross-collection: total + items)
- Placing an order that is not a draft (state machine rule, in `place()`)

**What this should NOT catch:**

- Whether the email is well-formed (that's Layer 2, in the `Email` VO)
- Whether the price is non-negative (that's Layer 1, on the field)
- Whether the user is authorized to place this order (that's Layer 4)

Aggregate invariants are the heart of domain validation. They express the
**business rules**, the things that make an order valid, an account consistent,
or a reservation enforceable.

---

## Layer 4: Handler and Service Guards

**What it validates:** Contextual rules that depend on the current operation,
the caller's identity, external state, or cross-aggregate conditions.

**Where it lives:** Command handlers, application services, event handlers,
and domain services.

**When it runs:** Before the aggregate method is called, in the handler or
service.

```python
--8<-- "patterns/validation-layering/003.py:guards"
```

**What this catches:**

- Authorization failures ("you don't have permission")
- Contextual time-based rules ("too late to cancel")
- Cross-aggregate constraints ("exceeds policy limit")
- External system state ("account is frozen in the external system")

**What this should NOT catch:**

- Field format validation (Layer 1)
- Value object consistency (Layer 2)
- Single-aggregate business rules (Layer 3)

---

## Command Validation

Commands validate their own fields at Layer 1, ensuring that the data
structure is correct before it reaches the handler:

```python
--8<-- "patterns/validation-layering/003.py:command"
```

If `total` is negative or `customer_id` is missing, the error is caught at
command construction, before the handler even runs. This is the earliest
possible feedback.

Commands should validate data structure and presence, not business rules.
"Is `customer_id` provided?" is a command concern. "Does this customer exist?"
is a handler concern.

---

## The Layers in Action

Consider a complete flow for placing an order with the `PlaceOrder` command
above:

```python
--8<-- "patterns/validation-layering/003.py:in_action"
```

Each layer catches different kinds of errors at progressively deeper levels
of the processing pipeline.

---

## Where Each Validation Type Belongs

| Validation Type | Layer | Location | Example |
|----------------|-------|----------|---------|
| Required fields | 1 | Field declaration | `name = String(required=True)` |
| Type constraints | 1 | Field declaration | `age = Integer(min_value=0)` |
| Format patterns | 2 | Value object invariant | `Email` format check |
| Internal consistency | 2 | Value object invariant | `DateRange` end > start |
| Currency validity | 2 | Value object invariant | `Money` valid currency |
| Cross-field rules | 3 | Aggregate invariant | Discount < total |
| State machine rules | 3 | Aggregate method | "Only draft orders can be placed" |
| Collection rules | 3 | Aggregate invariant | "Must have at least one item" |
| Authorization | 4 | Handler/service | "Only admins can cancel" |
| Cross-aggregate rules | 4 | Domain service | "Transfer within policy limits" |
| Time-based rules | 4 | Handler | "Within cancellation window" |
| External state | 4 | Handler/service | "Account not frozen" |

---

## Anti-Patterns

### Business Rules in Field Validators

```python
# fragment
# Anti-pattern: business rule encoded as a field constraint
class Order:
    discount_percent: Float(max_value=50.0)  # "Max 50% discount" is a business rule
```

This embeds a business rule in the field definition. When the business changes
the maximum discount to 60%, you're modifying the field schema instead of the
business rule layer. Use an invariant instead:

```python
--8<-- "patterns/validation-layering/004.py:discount_policy"
```

### Duplicating Validation Across Layers

```python
# fragment
# Anti-pattern: email validated in both VO and aggregate
@domain.value_object
class Email:
    address: String(required=True)

    @invariant.post
    def must_be_valid(self):
        if "@" not in self.address:
            raise ValidationError({"address": ["Invalid email"]})


@domain.aggregate
class User:
    email = ValueObject(Email, required=True)

    @invariant.post
    def email_must_be_valid(self):
        # REDUNDANT: Email VO already validates this
        if self.email and "@" not in self.email.address:
            raise ValidationError({"email": ["Invalid email"]})
```

The `Email` value object already validates format. The aggregate invariant
duplicates the check. Each layer should validate what the previous layers
don't cover.

### Authorization in Aggregate Invariants

```python
# fragment
# Anti-pattern: authorization check in aggregate
class Order:
    @invariant.post
    def only_admin_can_set_high_discount(self):
        # The aggregate shouldn't know about user roles
        if self.discount_percent > 20 and current_user().role != "admin":
            raise ValidationError(
                {"discount_percent": ["Only an admin can set a discount above 20%"]}
            )
```

The aggregate shouldn't access the current user or know about roles. That's
the handler's responsibility (Layer 4). The aggregate should validate the
domain rule: "discount cannot exceed 50%." The handler validates the
authorization rule: "only admins can set discounts above 20%."

### All Validation in the Handler

```python
# fragment
# Anti-pattern: all validation in the handler, aggregate is a data bag
@handle(PlaceOrder)
def place_order(self, command: PlaceOrder):
    # Handler does ALL validation
    if not command.items:
        raise ValidationError({"items": ["Required"]})
    if command.total < 0:
        raise ValidationError({"total": ["Must be positive"]})
    if "@" not in command.customer_email:
        raise ValidationError({"email": ["Invalid"]})
    if command.discount > command.total:
        raise ValidationError({"discount": ["Exceeds total"]})

    # Aggregate is just a data container
    order = Order(**command.to_dict())
    repo.add(order)
```

Every validation is in the handler. The aggregate has no invariants, no
protection. Any code that creates an `Order` (another handler, a test, an
import script) can create invalid instances. Distribute validation across
layers so each layer protects its own concerns.

---

## Summary

| Layer | What | Where | When | Example |
|-------|------|-------|------|---------|
| 1 - Field | Type, format, range, required | Field declarations | At construction/assignment | `String(max_length=200)` |
| 2 - Value Object | Concept-level rules | VO invariants | At VO construction | Email format, Money non-negative |
| 3 - Aggregate | Business rules | Aggregate invariants | After methods/mutations | Discount < total, must have items |
| 4 - Handler | Context, auth, cross-aggregate | Handlers/services | Before aggregate method call | Authorization, time-based rules |

Each validation layer has a specific scope. Field constraints catch data
errors. Value objects enforce concept rules. Aggregate invariants guard
business rules. Handlers check contextual and cross-aggregate conditions. Each
layer trusts the layers below it and adds what they don't cover.

---

!!! tip "Related reading"
    **Concepts:**

    - [Aggregates](../concepts/building-blocks/aggregates.md): Aggregate invariants and consistency.
    - [Value Objects](../concepts/building-blocks/value-objects.md): Value-level validation through invariants.

    **Guides:**

    - [Validations](../guides/domain-behavior/validations.md): Field restrictions, built-in validations, and custom validators.
    - [Invariants](../guides/domain-behavior/invariants.md): Pre and post invariants for business rules.
    - [Value Objects](../guides/domain-definition/value-objects.md): Embedding validation within value objects.
