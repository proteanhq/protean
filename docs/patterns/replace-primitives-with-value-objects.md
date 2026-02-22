# Replace Primitives with Value Objects

## The Problem

A developer models a `User` aggregate:

```python
@domain.aggregate
class User:
    user_id: Auto(identifier=True)
    name: String(required=True)
    email: String(required=True)
    phone: String()
    address_line1: String()
    address_line2: String()
    city: String()
    state: String()
    postal_code: String()
    country: String()
    balance_amount: Float(default=0.0)
    balance_currency: String(default="USD")
```

This compiles, tests pass, and the application works -- until it doesn't.

- A user signs up with `email="not-an-email"`. The system stores it, sends a
  welcome email, and the email bounces. The bounce handler crashes because it
  expected a valid email address.

- A financial report sums `balance_amount` across users in different currencies.
  The result is meaningless: you can't add USD and EUR. But the code doesn't
  know that -- they're just floats.

- A test creates a user with `country="United States"`, another with
  `country="US"`, and a third with `country="usa"`. The query for US users
  misses two-thirds of them.

- The address is six independent fields. To validate that a complete address
  was provided, the handler checks each field individually. To pass an address
  between methods, it passes six parameters. To compare two addresses, it
  compares six fields.

These problems share a root cause: **primitive obsession** -- using basic
types (strings, integers, floats) to represent domain concepts that have
structure, rules, and meaning beyond the primitive type's capabilities.

---

## The Pattern

Replace groups of related primitives and validated primitives with
**value objects** -- immutable domain objects that encapsulate their own
validation rules, are defined by their attributes (not identity), and make
invalid states unrepresentable.

```
Primitive obsession:
  email = String()                         # Accepts any string
  balance_amount = Float()                 # Accepts any number
  balance_currency = String()              # Disconnected from amount

Value objects:
  email = ValueObject(Email)               # Only valid emails
  balance = ValueObject(Money)             # Amount + currency, always together
```

### When to Extract a Value Object

Apply these tests to identify primitives that should be value objects:

1. **Format rules exist.** If a string must match a pattern (email, phone,
   postal code, URL), it's a value object. The validation should live with the
   data, not in every handler that touches it.

2. **Multiple fields travel together.** If two or more fields are meaningless
   alone but meaningful together (amount + currency, latitude + longitude,
   street + city + state + postal code), they form a value object.

3. **The same validation is duplicated.** If you're checking `if '@' in email`
   in multiple places, the validation belongs in a value object, written once.

4. **Equality is by value, not identity.** Two email addresses "user@example.com"
   are the same regardless of which user they belong to. Two `Money(100, "USD")`
   instances are equal. These are value objects.

5. **Operations exist.** If you can add two of them, compare them, or transform
   them, the operation logic should live in the value object. `Money` can be
   added (if currencies match). `DateRange` can check for overlaps.

---

## Applying the Pattern

### Email: Validated String

The simplest case -- a string with format rules.

**Before: primitive**

```python
@domain.aggregate
class User:
    user_id: Auto(identifier=True)
    email: String(required=True)

    @invariant.post
    def email_must_be_valid(self):
        if self.email and "@" not in self.email:
            raise ValidationError({"email": ["Invalid email address"]})
```

The validation is on the aggregate, but it's a concern of the email concept
itself, not the user. Every aggregate that has an email field must duplicate
this check.

**After: value object**

```python
@domain.value_object
class Email:
    address: String(required=True, max_length=254)

    @invariant.post
    def must_be_valid_format(self):
        if not self.address or "@" not in self.address:
            raise ValidationError(
                {"address": ["Must be a valid email address"]}
            )

        local, _, domain_part = self.address.partition("@")
        if not local or not domain_part or "." not in domain_part:
            raise ValidationError(
                {"address": ["Must be a valid email address"]}
            )


@domain.aggregate
class User:
    user_id: Auto(identifier=True)
    email = ValueObject(Email, required=True)
```

Now `Email` validates itself. Creating `Email(address="bad")` raises a
`ValidationError`. The `User` aggregate doesn't need an email validation
invariant. Any aggregate that uses `Email` gets validation automatically.

```python
# Valid
user = User(email=Email(address="user@example.com"))

# Invalid -- raises ValidationError at Email construction
user = User(email=Email(address="not-an-email"))
```

### Money: Compound Value

Two fields that are meaningless apart.

**Before: disconnected primitives**

```python
@domain.aggregate
class Product:
    product_id: Auto(identifier=True)
    name: String(required=True)
    price_amount: Float(required=True)
    price_currency: String(max_length=3, required=True)
    cost_amount: Float(required=True)
    cost_currency: String(max_length=3, required=True)
```

Can you calculate margin? `price_amount - cost_amount` -- but only if the
currencies match. Nothing enforces that. The currency fields are just strings.
You could set `price_currency="XYZ"` and the system would happily store it.

**After: value object with operations**

```python
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
        valid_currencies = {"USD", "EUR", "GBP", "JPY", "CAD", "AUD"}
        if self.currency not in valid_currencies:
            raise ValidationError(
                {"currency": [f"Currency must be one of {valid_currencies}"]}
            )

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValidationError(
                {"currency": ["Cannot add different currencies"]}
            )
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def subtract(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValidationError(
                {"currency": ["Cannot subtract different currencies"]}
            )
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def multiply(self, factor: float) -> "Money":
        return Money(amount=self.amount * factor, currency=self.currency)


@domain.aggregate
class Product:
    product_id: Auto(identifier=True)
    name: String(required=True)
    price = ValueObject(Money, required=True)
    cost = ValueObject(Money, required=True)

    def margin(self) -> Money:
        return self.price.subtract(self.cost)
```

Now `Money` enforces its own rules: non-negative amounts, valid currencies,
and same-currency arithmetic. The `Product` aggregate uses `Money` without
worrying about currency mismatches:

```python
product = Product(
    name="Widget",
    price=Money(amount=29.99, currency="USD"),
    cost=Money(amount=12.50, currency="USD"),
)

margin = product.margin()  # Money(amount=17.49, currency="USD")

# This raises ValidationError: "Cannot subtract different currencies"
bad_product = Product(
    name="Widget",
    price=Money(amount=29.99, currency="USD"),
    cost=Money(amount=12.50, currency="EUR"),
)
bad_product.margin()
```

### Address: Multi-Field Group

Six fields that form a single concept.

**Before: flat primitives**

```python
@domain.aggregate
class Customer:
    customer_id: Auto(identifier=True)
    name: String(required=True)
    shipping_street: String()
    shipping_city: String()
    shipping_state: String()
    shipping_postal_code: String()
    shipping_country: String()
    billing_street: String()
    billing_city: String()
    billing_state: String()
    billing_postal_code: String()
    billing_country: String()
```

Twelve address fields on one aggregate. To add a "work address," you'd add
five more. To validate that a complete address was provided, you check
each field individually.

**After: value object**

```python
@domain.value_object
class Address:
    street: String(required=True)
    city: String(required=True)
    state: String(required=True)
    postal_code: String(required=True)
    country: String(max_length=2, required=True)

    @invariant.post
    def country_must_be_iso_code(self):
        if len(self.country) != 2 or not self.country.isalpha():
            raise ValidationError(
                {"country": ["Country must be a 2-letter ISO code"]}
            )


@domain.aggregate
class Customer:
    customer_id: Auto(identifier=True)
    name: String(required=True)
    shipping_address = ValueObject(Address)
    billing_address = ValueObject(Address)
```

The aggregate went from twelve fields to two. Adding a work address is one
more field. The `Address` value object validates itself -- you can't create
a partial address with just a city and no street.

```python
customer = Customer(
    name="Jane Smith",
    shipping_address=Address(
        street="123 Main St",
        city="Springfield",
        state="IL",
        postal_code="62701",
        country="US",
    ),
    billing_address=Address(
        street="456 Oak Ave",
        city="Chicago",
        state="IL",
        postal_code="60601",
        country="US",
    ),
)
```

### DateRange: Value Object with Behavior

A concept with operations beyond storage.

```python
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

    def contains(self, date) -> bool:
        return self.start_date <= date <= self.end_date

    def overlaps(self, other: "DateRange") -> bool:
        return self.start_date <= other.end_date and other.start_date <= self.end_date

    def duration_days(self) -> int:
        return (self.end_date - self.start_date).days


@domain.aggregate
class Campaign:
    campaign_id: Auto(identifier=True)
    name: String(required=True)
    active_period = ValueObject(DateRange, required=True)

    def is_active_on(self, date) -> bool:
        return self.active_period.contains(date)
```

The `DateRange` value object knows how to check containment, overlap, and
duration. Without it, these operations would be scattered across handlers
and utility functions.

---

## How Protean Supports This

### The `ValueObject` Field

Protean's `ValueObject` association field embeds a value object directly inside
an aggregate or entity:

```python
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    total = ValueObject(Money, required=True)
    shipping_address = ValueObject(Address)
```

The value object is stored as part of the aggregate's data. When the aggregate
is persisted, the value object's fields are persisted alongside it. When loaded,
the value object is reconstructed automatically.

### Immutability Is Enforced

Protean enforces immutability on value objects. After construction, fields
cannot be changed:

```python
email = Email(address="user@example.com")
email.address = "other@example.com"  # Raises IncorrectUsageError
```

To "change" a value object, you replace it entirely:

```python
customer.shipping_address = Address(
    street="789 Pine St",
    city="Oakland",
    state="CA",
    postal_code="94607",
    country="US",
)
```

This aligns with the DDD principle: value objects are replaced, not mutated.

### No Identity Allowed

Protean explicitly rejects identifier fields on value objects:

```python
@domain.value_object
class Money:
    id: Auto(identifier=True)  # Raises IncorrectUsageError
    amount: Float()
    currency: String()
```

This enforces the distinction between entities (which have identity) and value
objects (which are defined by their attributes).

### Equality by Value

Two value objects with the same attributes are equal:

```python
money1 = Money(amount=100.0, currency="USD")
money2 = Money(amount=100.0, currency="USD")

assert money1 == money2  # True -- same attributes, same value object
```

This is automatic in Protean. You don't need to implement `__eq__`.

### Invariants on Value Objects

Value objects support `@invariant.post`, just like aggregates:

```python
@domain.value_object
class Percentage:
    value: Float(required=True)

    @invariant.post
    def must_be_between_zero_and_hundred(self):
        if not (0 <= self.value <= 100):
            raise ValidationError(
                {"value": ["Percentage must be between 0 and 100"]}
            )
```

The invariant fires at construction time. An invalid `Percentage` cannot exist.

---

## The Validation Shift

When you introduce value objects, validation naturally migrates from the
aggregate to the value object:

**Before: validation on the aggregate**

```python
@domain.aggregate
class User:
    email: String(required=True)
    phone: String()

    @invariant.post
    def email_must_be_valid(self):
        # Email validation on the User aggregate
        if self.email and "@" not in self.email:
            raise ValidationError({"email": ["Invalid email"]})

    @invariant.post
    def phone_must_be_valid(self):
        # Phone validation on the User aggregate
        if self.phone and not self.phone.replace("+", "").replace("-", "").isdigit():
            raise ValidationError({"phone": ["Invalid phone number"]})
```

**After: validation on the value objects**

```python
@domain.value_object
class Email:
    address: String(required=True, max_length=254)

    @invariant.post
    def must_be_valid(self):
        if "@" not in self.address:
            raise ValidationError({"address": ["Invalid email"]})


@domain.value_object
class Phone:
    number: String(required=True, max_length=20)

    @invariant.post
    def must_be_valid(self):
        digits = self.number.replace("+", "").replace("-", "").replace(" ", "")
        if not digits.isdigit():
            raise ValidationError({"number": ["Invalid phone number"]})


@domain.aggregate
class User:
    user_id: Auto(identifier=True)
    email = ValueObject(Email, required=True)
    phone = ValueObject(Phone)
    # No email or phone validation invariants needed on User
```

The aggregate's invariants now focus on **business rules** -- things like "a
user must have a verified email before they can place orders." Format validation
is the value object's responsibility.

---

## Nested Value Objects

Value objects can contain other value objects:

```python
@domain.value_object
class GeoLocation:
    latitude: Float(required=True)
    longitude: Float(required=True)

    @invariant.post
    def coordinates_must_be_valid(self):
        if not (-90 <= self.latitude <= 90):
            raise ValidationError(
                {"latitude": ["Latitude must be between -90 and 90"]}
            )
        if not (-180 <= self.longitude <= 180):
            raise ValidationError(
                {"longitude": ["Longitude must be between -180 and 180"]}
            )


@domain.value_object
class Address:
    street: String(required=True)
    city: String(required=True)
    state: String(required=True)
    postal_code: String(required=True)
    country: String(max_length=2, required=True)
    location = ValueObject(GeoLocation)  # Optional geo coordinates
```

An `Address` can optionally include a `GeoLocation`. Both are value objects,
both are immutable, and both validate themselves.

---

## Common Value Objects by Domain

### Universal Value Objects

These appear in nearly every domain:

| Value Object | Fields | Validation |
|-------------|--------|------------|
| `Email` | address | Format, max length |
| `Phone` | number, country_code | Format, valid prefix |
| `Money` | amount, currency | Non-negative, valid currency |
| `Address` | street, city, state, postal_code, country | Required fields, ISO country |
| `DateRange` | start_date, end_date | End after start |
| `Percentage` | value | Between 0 and 100 |
| `URL` | value | Valid URL format |

### Domain-Specific Value Objects

These emerge from your specific domain:

| Domain | Value Object | Fields | Validation |
|--------|-------------|--------|------------|
| E-commerce | `SKU` | code | Format, uniqueness pattern |
| E-commerce | `Weight` | value, unit | Positive, valid unit |
| Finance | `IBAN` | value | Checksum, country format |
| Healthcare | `BloodPressure` | systolic, diastolic | Ranges, systolic > diastolic |
| Logistics | `TrackingNumber` | carrier, number | Carrier-specific format |
| HR | `Salary` | amount, currency, period | Non-negative, valid period |

---

## When Not to Use Value Objects

### Truly Simple Strings

Not every string needs to be a value object. A `name` field with no format
rules, no operations, and no composition is fine as a `String`. Apply the
extraction tests from the beginning of this pattern -- if none apply, keep
the primitive.

### Performance-Critical Paths

Value objects add a small overhead: object construction, invariant checking,
and the wrapper object itself. In hot paths processing millions of records per
second, this overhead might matter. Profile before optimizing -- in most
applications, the overhead is negligible compared to database and network
latency.

### Fields That Are Truly Independent

If two fields happen to appear together but don't have a conceptual
relationship, don't force them into a value object. `created_at` and
`updated_at` often appear together but aren't a single concept -- they're
two independent timestamps.

---

## Anti-Patterns

### Wrapping Without Validating

```python
# Anti-pattern: value object that adds no value
@domain.value_object
class Name:
    value: String(required=True)
    # No validation, no operations, no composition
```

This adds complexity without benefit. A plain `String` field is simpler and
equally correct. Value objects earn their keep through validation, operations,
or composition.

### Mutable State Through Backdoors

```python
# Anti-pattern: trying to work around immutability
email = Email(address="old@example.com")
email._value_object_data["address"] = "new@example.com"  # Don't do this
```

Protean enforces immutability through `__setattr__`. Bypassing it breaks the
value object's guarantees. Replace the entire value object instead.

### Value Objects with Identity

If a concept has identity -- meaning two instances with the same attributes
can be different -- it's an entity, not a value object. A `BankAccount` with
a balance of $100 is not the same as another `BankAccount` with $100 -- they
have different identities. Use an entity or aggregate instead.

---

## Summary

| Aspect | Primitive Fields | Value Objects |
|--------|-----------------|---------------|
| Validation | Duplicated in each aggregate | Defined once in the VO |
| Invalid states | Possible (`email="bad"`) | Prevented at construction |
| Related fields | Scattered (`amount` + `currency`) | Grouped (`Money`) |
| Operations | Utility functions | Methods on the VO |
| Equality | N/A | By attribute values |
| Immutability | Not enforced | Enforced by Protean |
| Reusability | Copy-paste validation | Share the VO class |
| Readability | `shipping_street`, `shipping_city`, ... | `shipping_address` |

The principle: **if a primitive value has format rules, composition, or
operations, it's a value object. Extract it, validate it once, and let the
type system enforce your domain rules.**

---

!!! tip "Related reading"
    **Concepts:**

    - [Value Objects](../concepts/building-blocks/value-objects.md) — Immutable descriptive objects without identity.

    **Guides:**

    - [Value Objects](../guides/domain-definition/value-objects.md) — Defining, embedding, and validating value objects.
    - [Fields](../reference/fields/index.md) — Field types and configuration options.
