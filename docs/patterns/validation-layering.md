# Validation Layering

## The Problem

A developer adds email validation to a `User` aggregate:

```python
@domain.aggregate
class User:
    user_id: Auto(identifier=True)
    email: String(required=True, max_length=254)
    role: String(required=True, choices=["admin", "member", "guest"])

    @invariant.post
    def email_must_be_valid(self):
        if self.email and "@" not in self.email:
            raise ValidationError({"email": ["Invalid email format"]})

    @invariant.post
    def admin_must_have_company_email(self):
        if self.role == "admin" and not self.email.endswith("@company.com"):
            raise ValidationError(
                {"email": ["Admins must use a company email address"]}
            )
```

Two validations, both on the aggregate's invariants, but they serve different
purposes. The email format check is a universal truth about email addresses --
it applies regardless of context. The admin-company-email rule is a business
policy that could change, applies only to admins, and depends on the aggregate's
role field.

Mixing these creates problems:

- **Wrong error granularity.** A user entering `"bad-email"` gets a format
  error at the aggregate level, after the command is already processed. The
  error could have been caught earlier, at the field or value object level,
  with a clearer message.

- **Duplicated validation.** If `Email` is used in multiple aggregates
  (`User`, `Contact`, `Newsletter`), the format check is duplicated in each.
  If the format rule changes (e.g., accepting `+` in local parts), every
  aggregate must be updated.

- **Authorization mixed with domain rules.** "Only admins can cancel orders"
  is an authorization check, not a domain invariant. Putting it in the
  aggregate mixes infrastructure concerns with domain logic.

- **Validation at the wrong time.** A command with clearly invalid data
  (missing required fields, wrong types) travels through the system, gets
  deserialized, processed by a handler, applied to an aggregate -- all before
  the aggregate's invariant catches the error. The error surface is broad and
  the feedback is delayed.

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
@domain.aggregate
class Product:
    product_id: Auto(identifier=True)
    name: String(required=True, max_length=200)
    sku: String(required=True, max_length=20)
    price: Float(required=True, min_value=0.0)
    weight_kg: Float(min_value=0.0)
    stock_count: Integer(min_value=0, default=0)
    status: String(choices=["draft", "active", "discontinued"], default="draft")
```

**What this catches:**

- `name=None` when `required=True` → Validation error
- `name="x" * 201` when `max_length=200` → Validation error
- `price=-5.0` when `min_value=0.0` → Validation error
- `status="invalid"` when `choices=[...]` → Validation error
- `stock_count="abc"` when type is `Integer` → Type conversion error

**What this should NOT catch:**

- Business rules ("price must be higher than cost") -- that's Layer 3
- Cross-field validation ("if status is active, stock must be > 0") -- Layer 3
- Format patterns specific to domain concepts ("SKU must match XX-NNNN") --
  Layer 2

Field constraints are the first defense. They're declarative, visible in the
field definition, and enforced automatically by Protean.

---

## Layer 2: Value Object Invariants

**What it validates:** Rules intrinsic to a domain concept -- format patterns,
internal consistency, and constraints that define what makes a concept valid.

**Where it lives:** Invariants on value objects.

**When it runs:** At value object construction (which triggers during aggregate
construction or field assignment).

```python
@domain.value_object
class Email:
    address: String(required=True, max_length=254)

    @invariant.post
    def must_have_valid_format(self):
        if not self.address or "@" not in self.address:
            raise ValidationError(
                {"address": ["Must be a valid email address"]}
            )
        local, _, domain_part = self.address.partition("@")
        if not local or not domain_part or "." not in domain_part:
            raise ValidationError(
                {"address": ["Must be a valid email address"]}
            )


@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, required=True)

    @invariant.post
    def amount_must_be_non_negative(self):
        if self.amount < 0:
            raise ValidationError(
                {"amount": ["Amount cannot be negative"]}
            )

    @invariant.post
    def currency_must_be_valid(self):
        if self.currency not in {"USD", "EUR", "GBP", "JPY", "CAD"}:
            raise ValidationError(
                {"currency": [f"Invalid currency: {self.currency}"]}
            )


@domain.value_object
class DateRange:
    start_date: Date(required=True)
    end_date: Date(required=True)

    @invariant.post
    def end_must_be_after_start(self):
        if self.end_date <= self.start_date:
            raise ValidationError(
                {"end_date": ["End date must be after start date"]}
            )
```

**What this catches:**

- `Email(address="not-an-email")` → Invalid format
- `Money(amount=-5, currency="USD")` → Negative amount
- `Money(amount=10, currency="XYZ")` → Invalid currency
- `DateRange(start_date=today, end_date=yesterday)` → End before start

**What this should NOT catch:**

- Business rules about how the value is used in context ("Money amount must
  not exceed the account's credit limit") -- that's Layer 3
- Whether the current user is allowed to set this value -- that's Layer 4

Value object invariants are **context-free**. An `Email` is either valid or
not, regardless of which aggregate it's in or who is setting it.

---

## Layer 3: Aggregate Invariants

**What it validates:** Business rules that depend on the aggregate's state --
cross-field consistency, state machine rules, and domain-specific constraints.

**Where it lives:** Invariants on aggregates and entities.

**When it runs:** After aggregate methods are called (post-invariants) or
before specific operations (pre-invariants).

```python
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    items = HasMany(OrderItem)
    status: String(default="draft")
    total = ValueObject(Money)
    discount = ValueObject(Money)

    @invariant.post
    def must_have_items_when_placed(self):
        """An order cannot be placed without items."""
        if self.status != "draft" and not self.items:
            raise ValidationError(
                {"items": ["Order must have at least one item"]}
            )

    @invariant.post
    def discount_cannot_exceed_total(self):
        """Discount cannot be larger than the order total."""
        if (self.discount and self.total and
                self.discount.amount > self.total.amount):
            raise ValidationError(
                {"discount": ["Discount cannot exceed order total"]}
            )

    @invariant.post
    def total_must_match_items(self):
        """Order total must match sum of item totals."""
        if self.items and self.total:
            expected = sum(
                item.unit_price * item.quantity for item in self.items
            )
            if abs(self.total.amount - expected) > 0.01:
                raise ValidationError(
                    {"total": [
                        f"Total {self.total.amount} does not match "
                        f"items total {expected}"
                    ]}
                )
```

**What this catches:**

- Placing an order with no items (cross-field: status + items)
- Discount exceeding total (cross-field: discount + total)
- Total mismatch with item sum (cross-collection: total + items)

**What this should NOT catch:**

- Whether the email is well-formed (that's Layer 2, in the `Email` VO)
- Whether the price is non-negative (that's Layer 1, on the field)
- Whether the user is authorized to place this order (that's Layer 4)

Aggregate invariants are the heart of domain validation. They express the
**business rules** -- the things that make an order valid, an account
consistent, or a reservation enforceable.

---

## Layer 4: Handler and Service Guards

**What it validates:** Contextual rules that depend on the current operation,
the caller's identity, external state, or cross-aggregate conditions.

**Where it lives:** Command handlers, application services, event handlers,
and domain services.

**When it runs:** Before the aggregate method is called, in the handler or
service.

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):

    @handle(CancelOrder)
    def cancel_order(self, command: CancelOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)

        # Layer 4: Authorization check
        if command.cancelled_by_role != "admin" and command.cancelled_by != order.customer_id:
            raise ValidationError(
                {"authorization": ["Only the customer or an admin can cancel"]}
            )

        # Layer 4: Time-based business rule
        if order.placed_at and (datetime.now(timezone.utc) - order.placed_at).hours > 24:
            raise ValidationError(
                {"timing": ["Orders cannot be cancelled after 24 hours"]}
            )

        # Delegate to aggregate method (which has its own Layer 3 invariants)
        order.cancel(command.reason)
        repo.add(order)


@domain.domain_service(part_of=[Account, CreditPolicy])
class TransferValidationService:
    """Cross-aggregate validation that checks multiple aggregates."""

    @classmethod
    def validate_transfer(cls, source: Account, policy: CreditPolicy, amount: float):
        # Layer 4: Cross-aggregate business rule
        if amount > policy.max_single_transfer:
            raise ValidationError(
                {"amount": [
                    f"Transfer exceeds policy limit of {policy.max_single_transfer}"
                ]}
            )

        # Layer 4: External state check
        if source.is_frozen:
            raise ValidationError(
                {"account": ["Source account is frozen"]}
            )
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

## The Layers in Action

Consider a complete flow for placing an order:

```python
# --- Layer 1: Field Constraints ---
# Triggered at command construction
command = PlaceOrder(
    order_id="ord-123",
    customer_id="cust-456",
    items=[{"product_id": "prod-1", "quantity": 2, "unit_price": 29.99}],
    total=59.98,
    currency="USD",
)
# If order_id is missing → ValidationError (required field)
# If total is negative → ValidationError (min_value constraint)
# If currency is not a string → Type error


# --- Layer 4: Handler Guards ---
@handle(PlaceOrder)
def place_order(self, command: PlaceOrder):
    # Check customer credit status (cross-aggregate)
    credit = current_domain.repository_for(CustomerCredit).get(command.customer_id)
    if credit.is_suspended:
        raise ValidationError({"credit": ["Customer credit is suspended"]})

    # --- Layer 2: Value Object Invariants ---
    # Triggered when constructing the Money value object
    total = Money(amount=command.total, currency=command.currency)
    # If currency is "XYZ" → ValidationError (invalid currency in Money VO)

    # --- Layer 3: Aggregate Invariants ---
    order = Order(
        order_id=command.order_id,
        customer_id=command.customer_id,
        items=command.items,
        total=total,
    )
    order.place()
    # @invariant.post checks: must have items, total must match items
    # If no items → ValidationError
    # If total doesn't match → ValidationError

    current_domain.repository_for(Order).add(order)
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
# Anti-pattern: business rule encoded as a field constraint
class Order:
    discount_percent: Float(max_value=50.0)  # "Max 50% discount" is a business rule
```

This embeds a business rule in the field definition. When the business changes
the maximum discount to 60%, you're modifying the field schema instead of the
business rule layer. Use an invariant instead:

```python
class Order:
    discount_percent: Float(min_value=0.0, max_value=100.0)  # Physical range

    @invariant.post
    def discount_within_policy(self):
        if self.discount_percent > 50.0:
            raise ValidationError(
                {"discount_percent": ["Discount cannot exceed 50%"]}
            )
```

### Duplicating Validation Across Layers

```python
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
# Anti-pattern: authorization check in aggregate
class Order:
    @invariant.post
    def only_admin_can_set_high_discount(self):
        # The aggregate shouldn't know about user roles
        if self.discount_percent > 20 and current_user().role != "admin":
            raise ValidationError(...)
```

The aggregate shouldn't access the current user or know about roles. That's
the handler's responsibility (Layer 4). The aggregate should validate the
domain rule: "discount cannot exceed 50%." The handler validates the
authorization rule: "only admins can set discounts above 20%."

### All Validation in the Handler

```python
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

## Command Validation

Commands validate their own fields at Layer 1, ensuring that the data
structure is correct before it reaches the handler:

```python
@domain.command(part_of=Order)
class PlaceOrder(BaseCommand):
    order_id: Identifier(identifier=True)
    customer_id: Identifier(required=True)
    items: List(required=True)
    total: Float(required=True, min_value=0.0)
    currency: String(required=True, max_length=3)
```

If `total` is negative or `customer_id` is missing, the error is caught at
command construction -- before the handler even runs. This is the earliest
possible feedback.

Commands should validate data structure and presence, not business rules.
"Is `customer_id` provided?" is a command concern. "Does this customer exist?"
is a handler concern.

---

## Summary

| Layer | What | Where | When | Example |
|-------|------|-------|------|---------|
| 1 - Field | Type, format, range, required | Field declarations | At construction/assignment | `String(max_length=200)` |
| 2 - Value Object | Concept-level rules | VO invariants | At VO construction | Email format, Money non-negative |
| 3 - Aggregate | Business rules | Aggregate invariants | After methods/mutations | Discount < total, must have items |
| 4 - Handler | Context, auth, cross-aggregate | Handlers/services | Before aggregate method call | Authorization, time-based rules |

The principle: **each validation layer has a specific scope. Field constraints
catch data errors. Value objects enforce concept rules. Aggregate invariants
guard business rules. Handlers check contextual and cross-aggregate conditions.
Each layer trusts the layers below it and adds what they don't cover.**

---

!!! tip "Related reading"
    **Concepts:**

    - [Aggregates](../core-concepts/domain-elements/aggregates.md) — Aggregate invariants and consistency.
    - [Value Objects](../core-concepts/domain-elements/value-objects.md) — Value-level validation through invariants.

    **Guides:**

    - [Validations](../guides/domain-behavior/validations.md) — Field restrictions, built-in validations, and custom validators.
    - [Invariants](../guides/domain-behavior/invariants.md) — Pre and post invariants for business rules.
    - [Value Objects](../guides/domain-definition/value-objects.md) — Embedding validation within value objects.
