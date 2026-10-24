# Field Types Guide

## Simple Fields

### String

**Purpose**: Short text with length constraints: names, codes, statuses, emails

**Parameters**:
- `max_length` (default: 255): Maximum characters
- `min_length`: Minimum characters
- `sanitize` (default: off; set `True` per field, or domain-wide via `[field_defaults] sanitize`): Clean unsafe HTML with `bleach.clean()`: it escapes disallowed tags and removes disallowed attributes and HTML comments

**Examples**:
```python
# Basic string
name: String(required=True, max_length=100)

# With length constraints
sku: String(required=True, min_length=8, max_length=20)

# Enum-like with choices
status: String(choices=["draft", "published", "archived"])

# Identity field
order_id: String(required=True, identifier=True)
```

Emails and phone numbers need a validator: see [Validation Strategies](validation.md).

### Text

**Purpose**: Long text without length limits: descriptions, notes, HTML or Markdown content

**Parameters**:
- `sanitize` (default: off; set `True` per field, or domain-wide via `[field_defaults] sanitize`): Clean unsafe HTML with `bleach.clean()`: it escapes disallowed tags and removes disallowed attributes and HTML comments

**Examples**:
```python
description: Text()
content: Text(required=True)
```

### Integer

**Purpose**: Whole numbers: counts, quantities, ages, rankings, version numbers

**Parameters**:
- `min_value`: Minimum allowed value
- `max_value`: Maximum allowed value

**Examples**:
```python
# Positive count
view_count: Integer(default=0, min_value=0)

# Quantity with range
quantity: Integer(required=True, min_value=1, max_value=1000)

# Rating (1-5)
rating: Integer(required=True, min_value=1, max_value=5)
```

### Decimal

**Purpose**: Exact decimal numbers, stored as Python `decimal.Decimal`. Use it for money and
for any value where binary floating-point rounding is not acceptable.

**Parameters**:
- `precision`: Total number of digits
- `scale`: Digits after the decimal point
- `min_value`: Minimum allowed value
- `max_value`: Maximum allowed value

**Examples**:
```python
# Price with minimum
price: Decimal(required=True, precision=19, scale=4, min_value=0.01)

# Balance that starts at zero
balance: Decimal(precision=19, scale=4, default=0)
```

The field turns the ints, floats and strings you pass into `decimal.Decimal` values. Do your
arithmetic with `decimal.Decimal` too: adding a `float` to a `Decimal` raises `TypeError`.
Import the standard library class under another name (`from decimal import Decimal as D`)
so it does not clash with the `Decimal` field.

The field does not convert its `default`. With `default=0` the attribute holds the int `0`
until you assign a value. Arithmetic with `decimal.Decimal` still works, but `to_dict()`
emits `0` where an assigned value would emit a string, and a value object holding the
default does not compare equal to one built with `D("0")`.

**Note**: When an amount needs a currency, put both in a Money value object.

### Float

**Purpose**: Approximate (binary floating-point) numbers: percentages, measurements,
coordinates. Use `Decimal` for money and for any value that needs exact decimal math.

**Parameters**:
- `min_value`: Minimum allowed value
- `max_value`: Maximum allowed value

**Examples**:
```python
# Percentage (0-100)
discount_percent: Float(min_value=0.0, max_value=100.0, default=0.0)

# Temperature (can be negative)
temperature_celsius: Float(min_value=-273.15, max_value=1000.0)
```

### Boolean

**Purpose**: True/False flags. Use a `String` with `choices` when there are more than two
states.

**Examples**:
```python
is_active: Boolean(default=True)
can_edit: Boolean(required=True)
```

### Date

**Purpose**: Date without time

**Examples**:
```python
from datetime import date

birth_date: Date()
expires_on: Date(required=True)
```

### DateTime

**Purpose**: Date and time together: timestamps, scheduled times, deadlines with a time

**Examples**:
```python
from datetime import datetime, timezone

def utc_now():
    return datetime.now(timezone.utc)

# Created timestamp
created_at: DateTime(default=utc_now)

# Scheduled time
scheduled_at: DateTime(required=True)
```

## Association Fields

`HasOne`, `HasMany`, `ValueObject`, `Reference`, and the `Identifier` link to another
aggregate are covered in [Association Fields](associations.md).

## Special Fields

### Auto

**Purpose**: Auto-generated values. `Auto()` generates a UUID string; `Auto(increment=True)`
holds an integer sequence that the repository assigns when you add the aggregate.

**Examples**:
```python
# Usually automatic
id: Auto()  # Added automatically by Protean

# Auto-incrementing sequence
sequence_number: Auto(increment=True)
```

For user-provided IDs, use a `String` or `Integer` with `identifier=True`.

### Identifier

**Purpose**: Mark a field as an identity field: business identifiers (order_number, sku)
and natural keys, in place of the auto-generated id

**Examples**:
```python
@domain.aggregate
class Order:
    # Custom identifier instead of auto id
    order_number: String(required=True, identifier=True)

@domain.aggregate(auto_add_id_field=False)
class Product:
    # Disable auto id, use custom
    sku: String(required=True, identifier=True)
```

Value objects have no identity, so they take no identifier field.

### List

**Purpose**: List of simple values with no identity, such as tags or categories. Use
`HasMany` for objects with identity.

**Examples**:
```python
@domain.aggregate
class Article:
    title: String(required=True, max_length=200)

    # List of strings
    tags: List(content_type=String)

    # List of integers
    scores: List(content_type=Integer)

domain.init(traverse=False)

# Usage
with domain.domain_context():
    article = Article(title="Widgets", tags=["electronics", "gadgets", "new"])
```

### Dict

**Purpose**: Key-value pairs: metadata, configuration, flexible attributes. Define explicit
fields for structured data, and use a value object or an entity for a complex object.

**Examples**:
```python
@domain.aggregate
class Gadget:
    name: String(required=True, max_length=100)
    metadata: Dict()

domain.init(traverse=False)

# Usage
with domain.domain_context():
    gadget = Gadget(
        name="Widget",
        metadata={"color": "blue", "size": "medium", "weight": 1.5}
    )
```

## See Also

- [Validation Strategies](validation.md): Field validation options
- [Association Fields](associations.md): Detailed association patterns
- [Common Mistakes](common-mistakes.md): Anti-patterns to avoid
- Complete examples in [assets/](../assets/)
