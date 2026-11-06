# How Protean keeps domain objects always valid

What if your domain objects could never be invalid?

Most frameworks treat validation as something you do _to_ an object. You call
`validate()` or check `is_valid()`, and you hope each developer on the team ran
it before saving. Between those explicit checks, the object can exist in any
state: missing fields, broken business rules, impossible combinations. The
longer the object stays invalid, the more code reads and saves its invalid
data.

Protean checks validity on every change to a domain object. **Domain objects
are always valid, or they don't exist.** Protean automatically checks every
field assignment, every method call and every state transition against
constraints and business rules. If a change would violate any rule, it's
rejected immediately. The object stays in its previous valid state. A
`ValidationError` tells you exactly what went wrong.

Protean's validation isn't opt-in. It's the default. You don't write validation
middleware, call `clean()` methods, or wire up check pipelines. You declare
rules, and Protean enforces them continuously.

---

## Protean validates in four layers

Protean organizes validation into four distinct layers, each catching a
different category of error at a different point in the processing pipeline.

```
Layer 1: Field Constraints        →  Type safety, format, range
    ↓
Layer 2: Value Object Invariants  →  Domain concept rules
    ↓
Layer 3: Aggregate Invariants     →  Business rules, cross-field consistency
    ↓
Layer 4: Handler/Service Guards   →  Contextual rules, authorization
```

Each layer relies on the checks of the earlier layers and adds the checks they
don't cover. Together, they form a defense-in-depth strategy where invalid
state is caught at the earliest possible moment.

Let's build up an Order domain step by step to see each layer in action.

---

## Layer 1: Declare constraints on fields

The simplest layer. Declare types, ranges, required-ness, and allowed values
directly on the field. Protean enforces them on construction and on every
assignment.

```python
--8<-- "concepts/philosophy/always-valid/001.py:fields"
```

These constraints catch the most basic errors immediately:

```python
--8<-- "concepts/philosophy/always-valid/001.py:field_checks"
```

Field constraints are **declarative**: you see them in the field definition.
Protean enforces them automatically, so you never forget to run them.

**What belongs here:** Type checks, required-ness, string length limits,
numeric ranges, enumerated choices.

**What doesn't:** Business rules, format patterns for domain concepts,
cross-field validation.

---

## Layer 2: Give value objects their own invariants

Some concepts need their own validation. An email address isn't just a string.
It has structure. A monetary amount isn't just a float. It has a currency and
rules about sign. When a concept has internal rules, wrap it in a **value
object** with invariants.

```python
--8<-- "concepts/philosophy/always-valid/002.py:money"
```

Now use the `Money` value object in the Order:

```python hl_lines="8"
--8<-- "concepts/philosophy/always-valid/002.py:order"
```

The `Money` value object validates itself at construction. Suppose your code
creates `Money(amount=-5, currency="XYZ")`. The invariants run immediately,
before the value reaches the aggregate.

```python
--8<-- "concepts/philosophy/always-valid/002.py:money_checks"
```

Value object invariants are **context-free**. An `Email` is either valid or
not, regardless of which aggregate uses it. This eliminates duplication. You
define the format rule once in the value object, and every aggregate that uses
the value object applies it.

**What belongs here:** Format patterns (email, phone, SKU), internal
consistency (end date after start date), concept-level rules (non-negative
money).

**What doesn't:** Business rules about how the value is used in context
("discount cannot exceed order total").

---

## Layer 3: Enforce business rules with aggregate invariants

Business rules that span multiple fields or entities within the aggregate.
These rules define what makes an Order _valid_ as a business concept. They
check that the Order is internally consistent, beyond its fields having the
right types.

```python
--8<-- "concepts/philosophy/always-valid/003.py:setup"
--8<-- "concepts/philosophy/always-valid/003.py:aggregate"
```

These invariants run automatically:

```python
--8<-- "concepts/philosophy/always-valid/003.py:invariant_checks"
```

### Batching changes with `atomic_change`

Sometimes multiple changes are individually invalid but collectively valid.
Protean provides `atomic_change` for this:

```python
--8<-- "concepts/philosophy/always-valid/003.py:atomic_change"
```

Inside the block, invariant checks are suspended. A pre-check runs on entry
and a post-check runs on exit. If the final state is invalid, a
`ValidationError` is raised.

**What belongs here:** Cross-field consistency, state machine guards,
collection rules ("at least one item"), aggregate-level business rules.

**What doesn't:** Authorization checks, cross-aggregate constraints,
context-dependent rules.

---

## Layer 4: Guard requests in handlers and services

Some rules depend on context: who is making the request, what time it is, what
state other aggregates are in. You write these rules in command handlers,
application services, or domain services, outside the aggregate.

```python
--8<-- "concepts/philosophy/always-valid/004.py:handler"
```

**What belongs here:** Authorization ("only admins can..."), time-based rules,
cross-aggregate constraints, external state checks.

**What doesn't:** Field validation, value format rules, single-aggregate
business rules. Those belong in lower layers where they protect _every_ code
path, not just the handler.

---

## How does Protean enforce validity?

Protean enforces the always-valid guarantee by intercepting every field
assignment.

When you write `order.status = "confirmed"`, Protean's `__setattr__`
implementation does more than set a field:

1. **Pre-invariants** (`@invariant.pre`) run on the aggregate root: the guards
   that must hold _before_ the change is allowed.
2. **Field validation** runs: type checking, constraints, custom validators.
3. **The field is set.**
4. **Post-invariants** (`@invariant.post`) run on the aggregate root: the rules
   that must hold _after_ the change.

If any step fails, the change is rolled back. The aggregate stays in its
previous valid state.

This enforcement is **recursive**. When invariants run on the aggregate root,
Protean also walks all associated entities (via `HasOne` and `HasMany`) and
runs their invariants too. A child entity at any depth in the aggregate cannot
break its own rules without Protean raising an error.

```
order.status = "confirmed"
    │
    ├── Run @invariant.pre on Order
    ├── Validate "confirmed" against field constraints
    ├── Set the field
    ├── Run @invariant.post on Order
    │     ├── must_have_items_when_placed()
    │     └── total_must_match_items()
    └── Run @invariant.post on each OrderItem
          └── quantity_and_subtotal_consistent()
```

---

## What this means for your code

Because Protean enforces the always-valid guarantee, you write and think about
domain code differently:

- **No `validate()` calls**: You never need to remember to validate before
  saving. The aggregate cannot accept invalid state.

- **Named methods are safe**: A method like `order.place()` can modify multiple
  fields. Invariants check for inconsistency on each assignment. For
  coordinated mutations, you use `atomic_change`, which checks the final state
  on exit.

- **Handlers can't corrupt state**: Even if a command handler sets fields
  directly rather than using named methods, invariants still fire.

- **Tests are simpler**: Test business rules by directly setting fields and
  asserting that `ValidationError` is raised. No need to go through the full
  handler stack.

- **Invalid data is caught at the boundary**: Field constraints on commands
  catch bad data before handlers even run. Value object invariants catch format
  errors at construction. Aggregate invariants catch business rule violations
  immediately. Each layer runs its validation at the earliest point it can.

---

## Read more about validation

- [Validation Layering](../../patterns/validation-layering.md): Detailed
  pattern guide with anti-patterns and decision table for which layer to use.
- [Invariants (concept)](../foundations/invariants.md): Why invariants are
  fundamental to DDD and how they define aggregate boundaries.
- [Validations (guide)](../../guides/domain-behavior/validations.md): How-to
  for field constraints and custom validators.
- [Invariants (guide)](../../guides/domain-behavior/invariants.md): How-to
  for implementing pre/post invariants and using `atomic_change`.
