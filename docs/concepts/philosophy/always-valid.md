# The Always-Valid Domain

What if your domain objects could never be invalid?

Most frameworks treat validation as something you do _to_ an object -- call
`validate()`, check `is_valid()`, hope someone remembered to run it before
saving. Between those explicit checks, the object can exist in any state:
missing fields, broken business rules, impossible combinations. The longer
it stays invalid, the further the corruption spreads.

Protean takes a different approach. **Domain objects are always valid, or they
don't exist.** Every field assignment, every method call, every state transition
is automatically checked against constraints and business rules. If a change
would violate any rule, it's rejected immediately -- the object stays in its
previous valid state, and a `ValidationError` tells you exactly what went wrong.

This isn't opt-in. It's the default. You don't write validation middleware,
call `clean()` methods, or wire up check pipelines. You declare rules, and
Protean enforces them continuously.

---

## Four layers of protection

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

Each layer trusts the layers below it and adds what they don't cover. Together,
they form a defense-in-depth strategy where invalid state is caught at the
earliest possible moment.

Let's build up an Order domain step by step to see each layer in action.

---

## Layer 1: Field constraints

The simplest layer. Declare types, ranges, required-ness, and allowed values
directly on the field. Protean enforces them on construction and on every
assignment.

```python
from protean import Domain
from protean.fields import Float, HasMany, Identifier, Integer, String

domain = Domain()


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    status: String(max_length=20, default="draft")
    items = HasMany("OrderItem")


@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=0.01)
```

These constraints catch the most basic errors immediately:

```python
# Missing required field → ValidationError
order = Order()  # customer_id is required

# Type violation → ValidationError
item = OrderItem(product_name="Widget", quantity="abc", unit_price=10.0)

# Range violation → ValidationError
item = OrderItem(product_name="Widget", quantity=0, unit_price=10.0)
# quantity must be >= 1

# Even after construction, assignments are checked
item.unit_price = -5.0  # ValidationError: min_value is 0.01
```

Field constraints are **declarative** -- visible right in the field definition,
enforced automatically, never forgotten.

**What belongs here:** Type checks, required-ness, string length limits,
numeric ranges, enumerated choices.

**What doesn't:** Business rules, format patterns for domain concepts,
cross-field validation.

---

## Layer 2: Value object invariants

Some concepts deserve their own validation. An email address isn't just a
string -- it has structure. A monetary amount isn't just a float -- it has a
currency and rules about sign. When a concept has internal rules, wrap it in
a **value object** with invariants.

```python
from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, String

domain = Domain()


@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(required=True, max_length=3)

    @invariant.post
    def amount_must_be_non_negative(self):
        if self.amount < 0:
            raise ValidationError(
                {"amount": ["Amount cannot be negative"]}
            )

    @invariant.post
    def currency_must_be_recognized(self):
        valid = {"USD", "EUR", "GBP", "JPY", "CAD"}
        if self.currency not in valid:
            raise ValidationError(
                {"currency": [f"Unrecognized currency: {self.currency}"]}
            )
```

Now use it in the Order:

```python
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    status: String(max_length=20, default="draft")
    total = ValueObject(Money)
    items = HasMany("OrderItem")
```

The `Money` value object validates itself at construction. If someone tries to
create `Money(amount=-5, currency="XYZ")`, the invariants fire immediately --
before the value ever reaches the aggregate.

```python
# Invalid at construction → ValidationError
Money(amount=-5, currency="USD")   # "Amount cannot be negative"
Money(amount=10, currency="XYZ")   # "Unrecognized currency: XYZ"

# When assigned to an aggregate, the VO validates itself
order.total = Money(amount=50, currency="FAKE")  # ValidationError
```

Value object invariants are **context-free**. An `Email` is either valid or
not, regardless of which aggregate uses it. This eliminates duplication -- the
format rule lives in one place and is reused everywhere.

**What belongs here:** Format patterns (email, phone, SKU), internal
consistency (end date after start date), concept-level rules (non-negative
money).

**What doesn't:** Business rules about how the value is used in context
("discount cannot exceed order total").

---

## Layer 3: Aggregate invariants

Business rules that span multiple fields or entities within the aggregate.
These are the rules that define what makes an Order _valid_ as a business
concept -- not just that its fields have the right types, but that it's
internally consistent.

```python
from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, HasMany, Identifier, Integer, String, ValueObject

domain = Domain()


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    status: String(max_length=20, default="draft")
    total = ValueObject(Money)
    items = HasMany("OrderItem")

    @invariant.post
    def must_have_items_when_placed(self):
        if self.status != "draft" and not self.items:
            raise ValidationError(
                {"items": ["Order must have at least one item"]}
            )

    @invariant.post
    def total_must_match_items(self):
        if self.items and self.total:
            expected = sum(
                item.quantity * item.unit_price for item in self.items
            )
            if abs(self.total.amount - expected) > 0.01:
                raise ValidationError(
                    {"total": [
                        f"Total {self.total.amount} does not match "
                        f"items total {expected}"
                    ]}
                )
```

These invariants run automatically:

```python
# After construction
order = Order(
    customer_id="cust-1",
    status="confirmed",  # not draft, but no items → ValidationError
)

# After every field assignment
order.status = "confirmed"  # triggers post-invariants → checks items

# Recursively through child entities
order.add_items(OrderItem(product_name="Widget", quantity=2, unit_price=10.0))
# Post-invariants run on the aggregate root, checking all rules
```

### Batching changes with `atomic_change`

Sometimes multiple changes are individually invalid but collectively valid.
Protean provides `atomic_change` for this:

```python
from protean.core.aggregate import atomic_change

with atomic_change(order):
    order.total = Money(amount=120.0, currency="USD")
    order.add_items(OrderItem(
        product_name="Gadget", quantity=4, unit_price=30.0
    ))
# Invariants checked ONCE on exit -- both changes valid together
```

Inside the block, invariant checks are suspended. A pre-check runs on entry
and a post-check runs on exit. If the final state is invalid, a
`ValidationError` is raised.

**What belongs here:** Cross-field consistency, state machine guards,
collection rules ("at least one item"), aggregate-level business rules.

**What doesn't:** Authorization checks, cross-aggregate constraints,
context-dependent rules.

---

## Layer 4: Handler and service guards

Some rules depend on context: who is making the request, what time it is,
what state other aggregates are in. These rules live in command handlers,
application services, or domain services -- outside the aggregate.

```python
from datetime import datetime, timezone

from protean import handle
from protean.fields import Identifier, String
from protean.utils.globals import current_domain


@domain.command(part_of=Order)
class CancelOrder:
    order_id: Identifier(required=True)
    cancelled_by: Identifier(required=True)
    cancelled_by_role: String(required=True)
    reason: String(max_length=500)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(CancelOrder)
    def cancel_order(self, command: CancelOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)

        # Guard: authorization
        if (command.cancelled_by_role != "admin"
                and command.cancelled_by != order.customer_id):
            raise ValidationError(
                {"authorization": [
                    "Only the customer or an admin can cancel"
                ]}
            )

        # Guard: time-based business rule
        if order.placed_at:
            hours = (datetime.now(timezone.utc) - order.placed_at).total_seconds() / 3600
            if hours > 24:
                raise ValidationError(
                    {"timing": [
                        "Orders cannot be cancelled after 24 hours"
                    ]}
                )

        # Delegate to aggregate (which has its own Layer 3 invariants)
        order.cancel(command.reason)
        repo.add(order)
```

**What belongs here:** Authorization ("only admins can..."), time-based rules,
cross-aggregate constraints, external state checks.

**What doesn't:** Field validation, value format rules, single-aggregate
business rules -- those belong in lower layers where they protect _every_
code path, not just the handler.

---

## How it works under the hood

The always-valid guarantee isn't magic -- it's automatic interception.

When you write `order.status = "confirmed"`, Protean's `__setattr__`
implementation does more than set a field:

1. **Pre-invariants** (`@invariant.pre`) run on the aggregate root -- guards
   that must hold _before_ the change is allowed.
2. **Field validation** runs -- type checking, constraints, custom validators.
3. **The field is set.**
4. **Post-invariants** (`@invariant.post`) run on the aggregate root -- rules
   that must hold _after_ the change.

If any step fails, the change is rolled back. The aggregate stays in its
previous valid state.

This enforcement is **recursive**. When invariants run on the aggregate root,
Protean also walks all associated entities (via `HasOne` and `HasMany`) and
runs their invariants too. A child entity deep within the cluster cannot
silently violate its own rules.

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

The always-valid guarantee changes how you write and think about domain code:

- **No `validate()` calls.** You never need to remember to validate before
  saving. The aggregate simply cannot accept invalid state.

- **Named methods are safe.** A method like `order.place()` can modify multiple
  fields. Invariants catch any inconsistency on each assignment, or you use
  `atomic_change` for coordinated mutations.

- **Handlers can't corrupt state.** Even if a command handler sets fields
  directly rather than using named methods, invariants still fire.

- **Tests are simpler.** Test business rules by directly setting fields and
  asserting that `ValidationError` is raised. No need to go through the full
  handler stack.

- **Invalid data is caught at the boundary.** Field constraints on commands
  catch bad data before handlers even run. Value object invariants catch format
  errors at construction. Aggregate invariants catch business rule violations
  immediately. Each layer pushes validation as early as possible.

---

## Further reading

- [Validation Layering](../../patterns/validation-layering.md) -- Detailed
  pattern guide with anti-patterns and decision table for which layer to use.
- [Invariants (concept)](../foundations/invariants.md) -- Why invariants are
  fundamental to DDD and how they define aggregate boundaries.
- [Validations (guide)](../../guides/domain-behavior/validations.md) -- How-to
  for field constraints and custom validators.
- [Invariants (guide)](../../guides/domain-behavior/invariants.md) -- How-to
  for implementing pre/post invariants and using `atomic_change`.
