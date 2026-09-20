# Association Fields

This guide explains how to use association fields to create relationships between Protean domain elements.

## Overview

Protean provides four types of association fields:
1. **HasOne** - One-to-one relationship with an entity
2. **HasMany** - One-to-many relationship with entities
3. **ValueObject** - Embed an immutable value object
4. **Reference** - Reference another aggregate by ID

## HasOne (One-to-One Relationship)

### Purpose

Use `HasOne` when an aggregate or entity has exactly one related entity.

### Basic Usage

```python
from protean.fields import HasOne

@domain.aggregate
class Order:
    customer_id: String(required=True)
    shipping_info = HasOne("ShippingInfo")  # One-to-one

@domain.entity(part_of="Order")
class ShippingInfo:
    address: String(required=True, max_length=500)
    city: String(required=True, max_length=100)
    state: String(required=True, max_length=50)
    postal_code: String(required=True, max_length=20)
```

### Access Pattern

```python
# Create order with shipping info
order = Order(customer_id="C123")
order.shipping_info = ShippingInfo(
    address="123 Main St",
    city="New York",
    state="NY",
    postal_code="10001"
)

# Access directly
print(order.shipping_info.address)  # "123 Main St"

# Update
order.shipping_info.city = "Brooklyn"
```

### Optional vs Required

```python
# Optional (default)
shipping_info = HasOne("ShippingInfo")  # Can be None

# Required
shipping_info = HasOne("ShippingInfo", required=True)  # Must be set
```

### When to Use HasOne

**Use HasOne when**:
- One parent has exactly one child
- Child has identity (needs to be tracked separately)
- Child is mutable

**Examples**:
- Order has one ShippingInfo
- User has one Profile
- Invoice has one BillingDetails

**Don't use when**:
- Need multiple children (use HasMany)
- Data is immutable (use ValueObject)
- Referencing another aggregate (use Reference)

## HasMany (One-to-Many Relationship)

### Purpose

Use `HasMany` when an aggregate or entity has multiple related entities.

### Basic Usage

```python
from protean.fields import HasMany

@domain.aggregate
class Order:
    customer_id: String(required=True)
    line_items = HasMany("LineItem")  # One-to-many

@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True)

    @property
    def subtotal(self) -> float:
        return self.quantity * self.unit_price
```

### Auto-Generated Helper Methods

When you define a `HasMany` field, Protean automatically creates helper methods. For `line_items = HasMany("LineItem")`:

**Generated methods**:
- `add_line_items(item)` - Add one or more items
- `remove_line_items(item)` - Remove an item
- `get_one_from_line_items(identifier)` - Get item by ID
- `filter_line_items(**criteria)` - Filter items by criteria

**Important**: These methods are AUTO-GENERATED. Do NOT create them manually.

### Access Patterns

#### Adding Items

```python
order = Order(customer_id="C123")

# Add one item
item1 = LineItem(product_id="P1", quantity=2, unit_price=50.0)
order.add_line_items([item1])  # Auto-generated helper

# Add multiple items
items = [
    LineItem(product_id="P2", quantity=1, unit_price=100.0),
    LineItem(product_id="P3", quantity=3, unit_price=25.0)
]
order.add_line_items(items)  # Auto-generated helper
```

#### Accessing Items

```python
# Access collection
for item in order.line_items:
    print(f"Product: {item.product_id}, Qty: {item.quantity}")

# Get by index
first_item = order.line_items[0]

# Check if empty
if not order.line_items:
    print("No items in order")

# Count
item_count = len(order.line_items)
```

#### Finding Items

```python
# Get by identifier
item = order.get_one_from_line_items(item_id)  # Auto-generated

# Filter by criteria
expensive_items = order.filter_line_items(unit_price__gt=100.0)  # Auto-generated
product_items = order.filter_line_items(product_id="P1")  # Auto-generated
```

#### Removing Items

```python
# Remove specific item
order.remove_line_items(item)  # Auto-generated helper

# Remove by identifier
item = order.get_one_from_line_items(item_id)
order.remove_line_items(item)
```

### Custom Methods with HasMany

Only create custom methods when you need additional business logic beyond the auto-generated helpers:

```python
@domain.aggregate
class Order:
    line_items = HasMany("LineItem")
    # add_line_items(), remove_line_items() are auto-generated!

    def add_product(self, product_id: str, quantity: int, price: float):
        """Custom method with validation and business logic.

        Use this when you need MORE than just adding an item.
        Still uses the auto-generated add_line_items() under the hood.
        """
        # Custom validation
        if quantity > 100:
            raise ValueError("Quantity exceeds maximum per order")

        # Custom logic
        existing = self.filter_line_items(product_id=product_id)
        if existing:
            # Update existing item
            existing[0].quantity += quantity
        else:
            # Add new item using auto-generated helper
            item = LineItem(product_id=product_id, quantity=quantity, unit_price=price)
            self.add_line_items([item])

    @property
    def total(self) -> float:
        """Calculate order total."""
        return sum(item.subtotal for item in self.line_items)
```

### When to Use HasMany

**Use HasMany when**:
- One parent has multiple children
- Children have identity (tracked separately)
- Children are mutable
- Need to add/remove children dynamically

**Examples**:
- Order has many LineItems
- Post has many Comments
- ShoppingCart has many CartItems

**Don't use when**:
- Simple value collections (use List)
- Immutable data (use ValueObject)
- Referencing other aggregates (use Reference)

## ValueObject (Embedded Value Object)

### Purpose

Use `ValueObject` field to embed an immutable value object within an aggregate or entity.

### Basic Usage

```python
from protean.fields import ValueObject

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
    customer_id: String(required=True)
    total = ValueObject(Money, required=True)  # Embedded VO
```

### Initialization Patterns

#### Initialize with Object

```python
order = Order(
    customer_id="C123",
    total=Money(amount=100.0, currency="USD")
)
```

#### Initialize by Attributes

```python
# Flattened attribute names: {field_name}_{vo_field_name}
order = Order(
    customer_id="C123",
    total_amount=100.0,
    total_currency="USD"
)
```

Both produce identical results.

### Access Pattern

```python
# Access value object
print(order.total.amount)    # 100.0
print(order.total.currency)  # "USD"

# Use value object methods
shipping_cost = Money(amount=10.0, currency="USD")
grand_total = order.total.add(shipping_cost)
```

### Updating Value Objects

Value objects are immutable. Replace them entirely:

```python
# Wrong: Cannot modify
order.total.amount = 200.0  # Raises IncorrectUsageError

# Correct: Replace entire value object
order.total = Money(amount=200.0, currency="USD")
```

### Multiple Value Objects

```python
@domain.value_object
class Address:
    street: String(required=True, max_length=100)
    city: String(required=True, max_length=50)
    postal_code: String(required=True, max_length=20)

@domain.aggregate
class Order:
    customer_id: String(required=True)
    shipping_address = ValueObject(Address, required=True)
    billing_address = ValueObject(Address)  # Optional
    total = ValueObject(Money, required=True)
```

### When to Use ValueObject

**Use ValueObject when**:
- Multiple related attributes (amount + currency)
- Immutable data
- Complex validation rules
- Reusable across elements
- Behavior needed (methods like add(), format())

**Examples**:
- Money (amount + currency)
- Address (street + city + postal_code)
- Email (address with validation)
- DateRange (start_date + end_date)

**Don't use when**:
- Single simple value (use simple field)
- Mutable data (use Entity)
- Has identity (use Entity)

See [../assets/add_value_object_field.py](../assets/add_value_object_field.py) for complete example.

## Reference (Cross-Aggregate Reference)

### Purpose

Use `Reference` to reference another aggregate by ID without loading it.

### Basic Usage

```python
from protean.fields import Reference

@domain.aggregate
class Customer:
    name: String(required=True)
    email: String(required=True)

@domain.aggregate
class Order:
    customer = Reference("Customer")  # Reference by ID
    order_date: Date(required=True)
```

### Access Pattern

```python
# Create order with customer reference
order = Order(
    customer="CUST-123",  # Just the ID
    order_date=date.today()
)

# Access ID
customer_id = order.customer_id  # "CUST-123"

# Load full aggregate when needed
customer = domain.repository_for(Customer).get(order.customer_id)
print(customer.name)
```

### When to Use Reference

**Use Reference when**:
- Referencing another aggregate (maintain boundaries)
- Don't need full aggregate loaded
- Reduce coupling between aggregates
- Eventual consistency is acceptable

**Examples**:
- Order references Customer
- Invoice references Order
- Comment references User

**Don't use when**:
- Same aggregate (use HasOne/HasMany)
- Always need full data (consider denormalizing)
- Value objects (use ValueObject field)

## Choosing the Right Association

Use this decision tree:

```
What kind of relationship?

Same aggregate boundary?
├─ One-to-one with entity → HasOne
├─ One-to-many with entities → HasMany
└─ Immutable complex data → ValueObject

Cross-aggregate?
└─ Reference by ID → Reference

Simple collection?
├─ Values without identity → List
└─ Key-value pairs → Dict
```

## Complete Example

```python
from protean import Domain
from protean.fields import String, Integer, Float, HasOne, HasMany, ValueObject

domain = Domain()

# Value Object
@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

# Entities
@domain.entity(part_of="Order")
class ShippingInfo:
    address: String(required=True, max_length=500)
    city: String(required=True, max_length=100)

@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
    quantity: Integer(required=True, min_value=1)
    unit_price = ValueObject(Money, required=True)  # Embedded VO

    @property
    def line_total(self) -> Money:
        return Money(
            amount=self.unit_price.amount * self.quantity,
            currency=self.unit_price.currency
        )

# Aggregate
@domain.aggregate
class Order:
    customer_id: String(required=True)

    # HasOne association
    shipping_info = HasOne("ShippingInfo")

    # HasMany association (auto-generates helpers)
    line_items = HasMany("LineItem")

    # ValueObject field
    total = ValueObject(Money)

    def calculate_total(self) -> Money:
        """Calculate order total from line items."""
        if not self.line_items:
            return Money(amount=0.0, currency="USD")

        total = self.line_items[0].line_total
        for item in self.line_items[1:]:
            total = Money(
                amount=total.amount + item.line_total.amount,
                currency=total.currency
            )
        return total


# Usage
order = Order(customer_id="C123")

# Add shipping info (HasOne)
order.shipping_info = ShippingInfo(
    address="123 Main St",
    city="New York"
)

# Add line items (HasMany with auto-generated helper)
order.add_line_items([
    LineItem(
        product_id="P1",
        quantity=2,
        unit_price=Money(amount=50.0, currency="USD")
    )
])

# Calculate and set total
order.total = order.calculate_total()
```

## Common Patterns

### Pattern 1: HasMany with Calculation

```python
@domain.aggregate
class ShoppingCart:
    line_items = HasMany("CartItem")

    @property
    def item_count(self) -> int:
        """Total number of items."""
        return sum(item.quantity for item in self.line_items)

    @property
    def total(self) -> float:
        """Cart total."""
        return sum(item.subtotal for item in self.line_items)
```

### Pattern 2: HasOne with Validation

```python
@domain.aggregate
class Order:
    status: String(choices=["draft", "placed", "shipped"])
    shipping_info = HasOne("ShippingInfo")

    @invariant.post
    def placed_orders_must_have_shipping(self):
        if self.status in ["placed", "shipped"] and not self.shipping_info:
            raise ValidationError("Placed orders must have shipping info")
```

### Pattern 3: ValueObject in Entity

```python
@domain.entity(part_of="Customer")
class Address:
    street: String(required=True)
    location = ValueObject(Coordinates)  # VO in entity

@domain.value_object
class Coordinates:
    latitude: Float(required=True, min_value=-90.0, max_value=90.0)
    longitude: Float(required=True, min_value=-180.0, max_value=180.0)
```

## Anti-Patterns

### Anti-Pattern 1: Manually Creating Auto-Generated Methods

**Bad**:
```python
@domain.aggregate
class Order:
    line_items = HasMany("LineItem")

    # Don't do this - already auto-generated!
    def add_line_items(self, items):
        ...
```

**Good**:
```python
@domain.aggregate
class Order:
    line_items = HasMany("LineItem")
    # add_line_items() already exists automatically!

# Just use it
order.add_line_items([item1, item2])
```

### Anti-Pattern 2: Using HasMany for Simple Values

**Bad**:
```python
# Creating entities for simple strings
@domain.entity(part_of="Product")
class Tag:
    name: String(required=True)

@domain.aggregate
class Product:
    tags = HasMany("Tag")  # Overkill!
```

**Good**:
```python
@domain.aggregate
class Product:
    tags: List(content_type=String)  # Simple list
```

### Anti-Pattern 3: Using Primitives Instead of ValueObject

**Bad**:
```python
@domain.aggregate
class Order:
    total_amount: Float()
    total_currency: String()  # Scattered attributes
```

**Good**:
```python
@domain.aggregate
class Order:
    total = ValueObject(Money)  # Cohesive value object
```

### Anti-Pattern 4: Reference Within Same Aggregate

**Bad**:
```python
@domain.aggregate
class Order:
    line_items = Reference("LineItem")  # Wrong! Use HasMany
```

**Good**:
```python
@domain.aggregate
class Order:
    line_items = HasMany("LineItem")  # Correct for same aggregate
```

## See Also

- [Field Types Guide](field-types.md) - All available field types
- [Complete association example](../assets/add_association_fields.py)
- [ValueObject example](../assets/add_value_object_field.py)
- [aggregate](../aggregate/SKILL.md)
- [entity](../entity/SKILL.md)
- [value-object](../value-object/SKILL.md)
