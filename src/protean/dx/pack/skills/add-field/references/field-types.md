# Field Types Guide

This guide helps you choose the right Protean field type for your data.

## Overview

Protean provides field types in three categories:
1. **Simple fields** - For basic data types (text, numbers, dates, booleans)
2. **Association fields** - For relationships between domain elements
3. **Special fields** - For identity, auto-generation, and collections

## Simple Fields

### String

**Purpose**: Short text with length constraints

**Use for**:
- Names (customer name, product name)
- Codes (order number, SKU, status codes)
- Short descriptions
- Identifiers (email, username)

**Parameters**:
- `max_length` (default: 255) - Maximum characters
- `min_length` - Minimum characters
- `sanitize` (default: True) - Remove unsafe content

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

**When NOT to use**:
- Long text (use Text instead)
- Numbers (use Integer/Float)
- Emails/phones without validation (use custom validator)

### Text

**Purpose**: Long text without length limits

**Use for**:
- Long descriptions
- Content fields
- Notes and comments
- HTML/Markdown content

**Parameters**:
- `sanitize` (default: True) - Remove unsafe content

**Examples**:
```python
# Long description
description: Text()

# Content field
content: Text(required=True)

# Notes
notes: Text()
```

**When NOT to use**:
- Short text with length limits (use String)
- Structured data (use Dict or separate fields)

### Integer

**Purpose**: Whole numbers

**Use for**:
- Counts (view_count, stock_count)
- Quantities
- Ages
- Rankings
- Version numbers

**Parameters**:
- `min_value` - Minimum allowed value
- `max_value` - Maximum allowed value

**Examples**:
```python
# Positive count
view_count: Integer(default=0, min_value=0)

# Quantity with range
quantity: Integer(required=True, min_value=1, max_value=1000)

# Age with realistic range
age: Integer(min_value=0, max_value=150)

# Rating (1-5)
rating: Integer(required=True, min_value=1, max_value=5)
```

**When NOT to use**:
- Decimals (use Float)
- Large numbers that might overflow (use String for display)
- Money (use Float with Money value object)

### Float

**Purpose**: Decimal numbers

**Use for**:
- Money amounts
- Percentages
- Measurements (weight, height, distance)
- Calculations
- Ratings (4.5 stars)

**Parameters**:
- `min_value` - Minimum allowed value
- `max_value` - Maximum allowed value

**Examples**:
```python
# Price with minimum
price: Float(required=True, min_value=0.01)

# Percentage (0-100)
discount_percent: Float(min_value=0.0, max_value=100.0, default=0.0)

# Weight with reasonable bounds
weight_kg: Float(min_value=0.1, max_value=999.99)

# Temperature (can be negative)
temperature_celsius: Float(min_value=-273.15, max_value=1000.0)
```

**When NOT to use**:
- Counts (use Integer)
- Money without currency (use Money value object)
- Exact decimal math (Python Decimal issues)

**Note**: For money, prefer using a Money value object that combines amount and currency.

### Boolean

**Purpose**: True/False flags

**Use for**:
- Feature flags (is_active, is_verified, is_deleted)
- Status indicators (is_published, is_archived)
- Permissions (can_edit, can_delete)

**Examples**:
```python
# Active flag
is_active: Boolean(default=True)

# Verification status
is_verified: Boolean(default=False)

# Soft delete
is_deleted: Boolean(default=False)

# Permission flag
can_edit: Boolean(required=True)
```

**When NOT to use**:
- Multiple states (use String with choices)
- Nullable three-state logic (True/False/None is confusing)

### Date

**Purpose**: Date without time

**Use for**:
- Birth dates
- Expiry dates
- Deadlines (when time doesn't matter)
- Event dates

**Examples**:
```python
from datetime import date

# Birth date
birth_date: Date()

# Expiry date
expires_on: Date(required=True)

# Event date
event_date: Date(required=True)
```

**When NOT to use**:
- Timestamps (use DateTime)
- Date and time together (use DateTime)

### DateTime

**Purpose**: Date and time together

**Use for**:
- Timestamps (created_at, updated_at)
- Scheduled times
- Recorded events
- Deadlines with specific time

**Examples**:
```python
from datetime import datetime, timezone

def utc_now():
    return datetime.now(timezone.utc)

# Created timestamp
created_at: DateTime(default=utc_now)

# Updated timestamp
updated_at: DateTime(default=utc_now)

# Scheduled time
scheduled_at: DateTime(required=True)

# Deadline with time
deadline: DateTime()
```

**When NOT to use**:
- Date only (use Date)
- Time only (store as String or use DateTime with arbitrary date)

## Association Fields

### HasOne

**Purpose**: One-to-one relationship with an entity

**Use for**:
- One aggregate/entity has exactly one related entity
- Optional or required one-to-one

**Examples**:
```python
@domain.aggregate
class Order:
    # One order has one shipping info
    shipping_info = HasOne("ShippingInfo")

@domain.entity(part_of="Order")
class ShippingInfo:
    address: String(required=True, max_length=500)
    city: String(required=True, max_length=100)
```

**Access pattern**:
```python
order = Order(customer_id="C123")
order.shipping_info = ShippingInfo(address="123 Main St", city="NYC")

# Access directly
print(order.shipping_info.address)
```

**When NOT to use**:
- One-to-many (use HasMany)
- Immutable data (use ValueObject)
- Reference to another aggregate (use Reference)

### HasMany

**Purpose**: One-to-many relationship with entities

**Use for**:
- One aggregate/entity has multiple related entities
- Collections of child objects with identity

**Examples**:
```python
@domain.aggregate
class Order:
    # One order has many line items
    line_items = HasMany("LineItem")

@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
    quantity: Integer(required=True, min_value=1)
```

**Auto-generated methods**:
- `add_line_items(item)` - Add items
- `remove_line_items(item)` - Remove item
- `get_one_from_line_items(id)` - Get by ID
- `filter_line_items(**criteria)` - Filter items

**Access pattern**:
```python
order = Order(customer_id="C123")
item = LineItem(product_id="P1", quantity=2)
order.add_line_items([item])  # Auto-generated helper

# Access collection
for item in order.line_items:
    print(item.product_id)
```

**When NOT to use**:
- Simple value lists (use List)
- Immutable data (use ValueObject)
- Reference to another aggregate (use Reference)

### ValueObject

**Purpose**: Embed an immutable value object

**Use for**:
- Complex immutable data (Money, Address, Email)
- Multiple related attributes (amount + currency)
- Reusable concepts across elements
- Data with behavior

**Examples**:
```python
@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("Currency mismatch")
        return Money(amount=self.amount + other.amount, currency=self.currency)

@domain.aggregate
class Order:
    # Embedded value object
    total = ValueObject(Money, required=True)
```

**Initialization**:
```python
# With object
order = Order(
    customer_id="C123",
    total=Money(amount=100.0, currency="USD")
)

# By attributes
order = Order(
    customer_id="C123",
    total_amount=100.0,
    total_currency="USD"
)
```

**When NOT to use**:
- Single simple value (use simple field)
- Mutable data (use Entity)
- Reference to another aggregate (use Reference)

### Reference

**Purpose**: Reference another aggregate by ID

**Use for**:
- Cross-aggregate relationships
- Avoid loading full aggregate
- Maintain aggregate boundaries

**Examples**:
```python
@domain.aggregate
class Order:
    # Reference Customer aggregate
    customer = Reference("Customer")

@domain.aggregate
class Customer:
    name: String(required=True)
    email: String(required=True)
```

**Access pattern**:
```python
order = Order(customer="CUST-123")  # Just the ID

# Get ID
customer_id = order.customer_id

# Load full aggregate if needed
customer = domain.repository_for(Customer).get(order.customer_id)
```

**When NOT to use**:
- Entities within same aggregate (use HasOne/HasMany)
- Value objects (use ValueObject field)

## Special Fields

### Auto

**Purpose**: Auto-generated values (usually IDs)

**Use for**:
- Auto-generated IDs
- Auto-incrementing values

**Examples**:
```python
# Usually automatic
id: Auto()  # Added automatically by Protean

# Custom auto field
sequence_number: Auto()
```

**When NOT to use**:
- User-provided IDs (use String/Integer with identifier=True)
- UUIDs you want to control

### Identifier

**Purpose**: Mark a field as an identity field

**Use for**:
- Business identifiers (order_number, sku)
- Natural keys
- Alternative to auto-generated ID

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

**When NOT to use**:
- Non-unique fields
- Value objects (they don't have identity)

### List

**Purpose**: List of simple values

**Use for**:
- Simple collections (tags, categories)
- No identity needed
- Primitive types

**Examples**:
```python
# List of strings
tags: List(content_type=String)

# List of integers
scores: List(content_type=Integer)

# Usage
product = Product(
    name="Widget",
    tags=["electronics", "gadgets", "new"]
)
```

**When NOT to use**:
- Complex objects with identity (use HasMany)
- Key-value pairs (use Dict)

### Dict

**Purpose**: Dictionary/mapping of key-value pairs

**Use for**:
- Metadata
- Configuration
- Flexible attributes

**Examples**:
```python
# Metadata
metadata: Dict()

# Configuration
settings: Dict()

# Usage
product = Product(
    name="Widget",
    metadata={"color": "blue", "size": "medium", "weight": 1.5}
)
```

**When NOT to use**:
- Structured data (define explicit fields)
- Complex objects (use ValueObject or Entity)

## Decision Tree

Use this tree to choose the right field type:

```
Is it a relationship to another element?
├─ Yes → Association field (HasOne, HasMany, ValueObject, Reference)
└─ No → Continue

Is it a simple value?
├─ Text?
│  ├─ Short (< 255 chars) → String
│  └─ Long → Text
├─ Number?
│  ├─ Whole number → Integer
│  └─ Decimal → Float
├─ True/False? → Boolean
├─ Date?
│  ├─ Date only → Date
│  └─ Date + time → DateTime
└─ Collection?
   ├─ Simple values → List
   └─ Key-value pairs → Dict
```

## Common Questions

**Q: String or Text for descriptions?**
A: String if under 255 chars and you want length validation. Text for longer content.

**Q: Integer or Float for money?**
A: Neither - use Float with a Money value object (includes currency).

**Q: HasMany or List for collections?**
A: HasMany for entities with identity. List for simple values.

**Q: When to use ValueObject field?**
A: When you have multiple related attributes (amount + currency), complex validation, or behavior.

**Q: String or DateTime for dates?**
A: DateTime for proper date handling. String only for display formats.

## See Also

- [Validation Strategies](validation.md) - Field validation options
- [Association Fields](associations.md) - Detailed association patterns
- [Common Mistakes](common-mistakes.md) - Anti-patterns to avoid
- Complete examples in [assets/](../assets/)
