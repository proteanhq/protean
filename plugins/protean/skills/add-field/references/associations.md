# Association Fields

This guide explains how to use association fields to create relationships between Protean domain elements.

## Overview

Protean provides four types of association fields:
1. **HasOne** - One-to-one relationship with an entity
2. **HasMany** - One-to-many relationship with entities
3. **ValueObject** - Embed an immutable value object
4. **Reference** - Link an entity back to its own aggregate root

To link to a *different* aggregate, do not use an association field. Store the other
aggregate's id in an `Identifier` field. See [Linking to Another Aggregate](#linking-to-another-aggregate).

## HasOne (One-to-One Relationship)

### Purpose

Use `HasOne` when an aggregate or entity has exactly one related entity.

### Basic Usage

```python
from protean.fields import HasOne

@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
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
domain.init(traverse=False)

with domain.domain_context():
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
# fragment
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
- Linking to another aggregate (use an `Identifier` field)

## HasMany (One-to-Many Relationship)

### Purpose

Use `HasMany` when an aggregate or entity has multiple related entities.

### Basic Usage

```python
from decimal import Decimal as D

from protean.fields import HasMany

@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    line_items = HasMany("LineItem")  # One-to-many

@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
    quantity: Integer(required=True, min_value=1)
    unit_price: Decimal(required=True, precision=19, scale=4)

    @property
    def subtotal(self) -> D:
        return self.quantity * self.unit_price
```

### Auto-Generated Helper Methods

When you define a `HasMany` field, Protean automatically creates helper methods. For `line_items = HasMany("LineItem")`:

**Generated methods**:
- `add_line_items(item)` - Add one or more items
- `remove_line_items(item)` - Remove an item
- `get_one_from_line_items(id=item_id)` - Get one item by keyword criteria
- `filter_line_items(**criteria)` - Get the items whose fields equal the given values

Both take keyword arguments only. `filter_line_items` matches equality only: it does not
support operators such as `unit_price__gt`. `get_one_from_line_items` raises
`ObjectNotFoundError` (from `protean.exceptions`) when no item matches. It never returns `None`.

**Important**: These methods are AUTO-GENERATED. Do NOT create them manually.

### Access Patterns

#### Adding Items

```python
domain.init(traverse=False)

with domain.domain_context():
    order = Order(customer_id="C123")

    # Add one item
    item1 = LineItem(product_id="P1", quantity=2, unit_price=D("50.00"))
    order.add_line_items([item1])  # Auto-generated helper

    # Add multiple items
    items = [
        LineItem(product_id="P2", quantity=1, unit_price=D("150.00")),
        LineItem(product_id="P3", quantity=3, unit_price=D("25.00"))
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
from protean.exceptions import ObjectNotFoundError

# Get by identifier (keyword argument)
item = order.get_one_from_line_items(id=item1.id)  # Auto-generated

# A miss raises ObjectNotFoundError
try:
    order.get_one_from_line_items(id="no-such-item")
except ObjectNotFoundError:
    print("No such line item")

# Filter by equality
product_items = order.filter_line_items(product_id="P1")  # Auto-generated

# For comparisons, filter the collection in Python
expensive_items = [i for i in order.line_items if i.unit_price > D("100")]
```

#### Removing Items

```python
# Remove specific item
order.remove_line_items(item)  # Auto-generated helper

# Remove by identifier
other = order.get_one_from_line_items(id=items[0].id)
order.remove_line_items(other)
```

### Custom Methods with HasMany

Only create custom methods when you need additional business logic beyond the auto-generated helpers:

```python
@domain.aggregate
class Order:
    line_items = HasMany("LineItem")
    # add_line_items(), remove_line_items() are auto-generated!

    def add_product(self, product_id: str, quantity: int, price: D):
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
    def total(self) -> D:
        """Calculate order total."""
        return sum((item.subtotal for item in self.line_items), D("0"))
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
- Linking to other aggregates (use an `Identifier` field)

## ValueObject (Embedded Value Object)

### Purpose

Use `ValueObject` field to embed an immutable value object within an aggregate or entity.

### Basic Usage

```python
from protean.fields import ValueObject

@domain.value_object
class Money:
    amount: Decimal(required=True, precision=19, scale=4)
    currency: String(max_length=3, default="USD")

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("Currency mismatch")
        return Money(amount=self.amount + other.amount, currency=self.currency)

@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    total = ValueObject(Money, required=True)  # Embedded VO
```

### Initialization Patterns

#### Initialize with Object

```python
domain.init(traverse=False)

with domain.domain_context():
    order = Order(
        customer_id="C123",
        total=Money(amount=D("100.00"), currency="USD")
    )
```

#### Initialize by Attributes

```python
with domain.domain_context():
    # Flattened attribute names: {field_name}_{vo_field_name}
    order = Order(
        customer_id="C123",
        total_amount=D("100.00"),
        total_currency="USD"
    )
```

Both produce identical results.

### Access Pattern

```python
with domain.domain_context():
    # Access value object
    print(order.total.amount)    # Decimal('100.00')
    print(order.total.currency)  # "USD"

    # Use value object methods
    shipping_cost = Money(amount=D("10.00"), currency="USD")
    grand_total = order.total.add(shipping_cost)
```

### Updating Value Objects

Value objects are immutable. Replace them entirely:

```python
# fragment
# Wrong: Cannot modify
order.total.amount = D("200.00")  # Raises IncorrectUsageError
```

```python
with domain.domain_context():
    # Correct: Replace entire value object
    order.total = Money(amount=D("200.00"), currency="USD")
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
    customer_id: Identifier(required=True)
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

## Reference (Link Back to the Aggregate Root)

### Purpose

Use `Reference` on an entity to point at its own aggregate root. It is the reverse side of
a `HasMany` or `HasOne` field. The `Reference` named `post` stores the root's id in
`post_id` and gives access to the root object through `post`.

### Basic Usage

```python
from protean.fields import Reference

@domain.aggregate
class Post:
    title = String(required=True, max_length=200)
    comments = HasMany("Comment")

@domain.entity(part_of="Post")
class Comment:
    body = Text(required=True)
    post = Reference("Post")  # The root this comment belongs to
```

When you leave the `Reference` out, `HasMany` and `HasOne` add it to the entity for you,
named after the aggregate. Declare it yourself when you want a different name.

### Access Pattern

```python
domain.init(traverse=False)

with domain.domain_context():
    post = Post(title="Hello")
    comment = Comment(body="Nice post")
    post.add_comments(comment)

    print(comment.post_id == post.id)  # True
    print(comment.post is post)        # True
```

### When to Use Reference

**Use Reference when**:
- An entity needs to point at the aggregate root it belongs to

**Don't use when**:
- Linking to another aggregate (use an `Identifier` field)
- Linking a root to its children (use HasOne/HasMany)

`protean check` reports a `Reference` to another aggregate as `CROSS_AGGREGATE_REFERENCE`.

## Linking to Another Aggregate

### Purpose

Aggregates link to each other by id only. Add an `Identifier` field that holds the other
aggregate's id. Each aggregate stays its own consistency boundary, and you load the other
one through its repository only when you need it.

### Basic Usage

```python
from datetime import date

@domain.aggregate
class Customer:
    name = String(required=True, max_length=100)
    email = String(required=True, max_length=254)

@domain.aggregate
class Shipment:
    customer_id = Identifier(required=True)  # Holds the Customer's id
    shipped_on = Date(required=True)
```

### Access Pattern

```python
domain.init(traverse=False)

with domain.domain_context():
    customer = Customer(name="Jane Doe", email="jane@example.com")
    domain.repository_for(Customer).add(customer)

    # Store only the id
    shipment = Shipment(customer_id=customer.id, shipped_on=date.today())

    # Load the full aggregate when you need it
    loaded = domain.repository_for(Customer).get(shipment.customer_id)
    print(loaded.name)  # "Jane Doe"
```

### When to Use an Identifier Link

**Use an `Identifier` field when**:
- The other object is an aggregate with its own lifecycle
- You don't need the other aggregate loaded with this one
- Eventual consistency between the two is acceptable

**Examples**:
- Order holds `customer_id`
- Invoice holds `order_id`
- Comment holds `author_id` (the User aggregate)

**Don't use when**:
- The other object is inside the same aggregate (use HasOne/HasMany)
- The data is a value with no identity (use a ValueObject field)
- You always need the other aggregate's data (copy the fields you need)

## Choosing the Right Association

Use this decision tree:

```
What kind of relationship?

Same aggregate boundary?
├─ One-to-one with entity → HasOne
├─ One-to-many with entities → HasMany
└─ Immutable complex data → ValueObject

Entity pointing at its own aggregate root?
└─ Reference (HasOne/HasMany add it for you)

Another aggregate?
└─ Store its id → Identifier

Simple collection?
├─ Values without identity → List
└─ Key-value pairs → Dict
```

## Complete Example

```python
from decimal import Decimal as D

from protean import Domain
from protean.fields import Decimal, HasMany, HasOne, Identifier, Integer, String, ValueObject

domain = Domain()

# Value Object
@domain.value_object
class Money:
    amount: Decimal(required=True, precision=19, scale=4)
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
    customer_id: Identifier(required=True)

    # HasOne association
    shipping_info = HasOne("ShippingInfo")

    # HasMany association (auto-generates helpers)
    line_items = HasMany("LineItem")

    # ValueObject field
    total = ValueObject(Money)

    def calculate_total(self) -> Money:
        """Calculate order total from line items."""
        if not self.line_items:
            return Money(amount=D("0"), currency="USD")

        total = self.line_items[0].line_total
        for item in self.line_items[1:]:
            total = Money(
                amount=total.amount + item.line_total.amount,
                currency=total.currency
            )
        return total


# Usage
domain.init(traverse=False)

with domain.domain_context():
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
            unit_price=Money(amount=D("50.00"), currency="USD")
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
    def total(self) -> D:
        """Cart total."""
        return sum((item.subtotal for item in self.line_items), D("0"))

@domain.entity(part_of="ShoppingCart")
class CartItem:
    product_id = Identifier(required=True)
    quantity = Integer(required=True, min_value=1)
    unit_price = Decimal(required=True, precision=19, scale=4)

    @property
    def subtotal(self) -> D:
        return self.quantity * self.unit_price
```

### Pattern 2: HasOne with Validation

```python
from protean.exceptions import ValidationError

@domain.aggregate
class Order:
    status: String(choices=["draft", "placed", "shipped"])
    shipping_info = HasOne("ShippingInfo")

    @invariant.post
    def placed_orders_must_have_shipping(self):
        if self.status in ["placed", "shipped"] and not self.shipping_info:
            raise ValidationError(
                {"shipping_info": ["Placed orders must have shipping info"]}
            )

@domain.entity(part_of="Order")
class ShippingInfo:
    address: String(required=True, max_length=500)
    city: String(required=True, max_length=100)
```

### Pattern 3: ValueObject in Entity

```python
@domain.aggregate
class Customer:
    name = String(required=True, max_length=100)
    addresses = HasMany("Address")

@domain.entity(part_of="Customer")
class Address:
    street: String(required=True)
    location = ValueObject("Coordinates")  # VO in entity

@domain.value_object
class Coordinates:
    latitude: Float(required=True, min_value=-90.0, max_value=90.0)
    longitude: Float(required=True, min_value=-180.0, max_value=180.0)
```

## Anti-Patterns

### Anti-Pattern 1: Manually Creating Auto-Generated Methods

**Bad**:
```python
# fragment
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
    customer_id = Identifier(required=True)
    line_items = HasMany("LineItem")
    # add_line_items() already exists automatically!

@domain.entity(part_of="Order")
class LineItem:
    product_id = Identifier(required=True)
    quantity = Integer(required=True, min_value=1)

domain.init(traverse=False)

# Just use it
with domain.domain_context():
    order = Order(customer_id="C123")
    item1 = LineItem(product_id="P1", quantity=1)
    item2 = LineItem(product_id="P2", quantity=2)
    order.add_line_items([item1, item2])
```

### Anti-Pattern 2: Using HasMany for Simple Values

**Bad**:
```python
# fragment
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
# fragment
@domain.aggregate
class Order:
    total_amount: Decimal(precision=19, scale=4)
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
# fragment
@domain.aggregate
class Order:
    line_items = Reference("LineItem")  # Wrong! Use HasMany
```

**Good**:
```python
@domain.aggregate
class Order:
    customer_id = Identifier(required=True)
    line_items = HasMany("LineItem")  # Correct for same aggregate

@domain.entity(part_of="Order")
class LineItem:
    product_id = Identifier(required=True)
    quantity = Integer(required=True, min_value=1)
```

### Anti-Pattern 5: Reference to Another Aggregate

**Bad**:
```python
# fragment
@domain.aggregate
class Order:
    customer = Reference("Customer")  # Customer is another aggregate
```

`protean check` reports this as `CROSS_AGGREGATE_REFERENCE`.

**Good**:
```python
@domain.aggregate
class Order:
    customer_id = Identifier(required=True)  # Holds the Customer's id
    line_items = HasMany("LineItem")

@domain.entity(part_of="Order")
class LineItem:
    product_id = Identifier(required=True)
    quantity = Integer(required=True, min_value=1)
```

## See Also

- [Field Types Guide](field-types.md) - All available field types
- [Complete association example](../assets/add_association_fields.py)
- [ValueObject example](../assets/add_value_object_field.py)
- [aggregate](../../aggregate/SKILL.md)
- [entity](../../entity/SKILL.md)
- [value-object](../../value-object/SKILL.md)
