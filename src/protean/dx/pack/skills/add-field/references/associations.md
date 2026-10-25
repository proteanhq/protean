# Association Fields

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

The SKILL.md describes the four methods `HasMany` generates. For
`line_items = HasMany("LineItem")` they are `add_line_items`, `remove_line_items`,
`get_one_from_line_items` and `filter_line_items`. The last two take keyword arguments only.
Do not define these methods yourself.

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
assert item is item1

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
assert other is items[0]
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

        Use this when you need more than adding an item. It still adds
        new items through the generated add_line_items().
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

**Don't use when**:
- Single simple value (use simple field)
- Mutable data (use Entity)
- Has identity (use Entity)

See [../assets/add_value_object_field.py](../assets/add_value_object_field.py) for complete example.

## Reference (Link Back to the Parent)

### Purpose

Use `Reference` on an entity to point at its parent: the aggregate root, or the parent entity
when the entity is nested. It is the reverse side of a `HasMany` or `HasOne` field. The
`Reference` named `post` stores the root's id in `post_id` and gives access to the root object
through `post`.

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

An `Identifier` field stores the id as a string, so an `Integer` id of `42` comes back as
`"42"`, and `repository_for(...).get("42")` does not find an aggregate whose id field is
`Integer(identifier=True)`. Give the target aggregate the default id or a `String` id.

### When to Use an Identifier Link

**Use an `Identifier` field when**:
- The other object is an aggregate with its own lifecycle
- You don't need the other aggregate loaded with this one
- Eventual consistency between the two is acceptable

**Don't use when**:
- The other object is inside the same aggregate (use HasOne/HasMany)
- The data is a value with no identity (use a ValueObject field)
- You always need the other aggregate's data (copy the fields you need)

## Common Patterns

### Pattern 1: HasOne with Validation

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

### Pattern 2: ValueObject in Entity

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

## See Also

- [Field Types Guide](field-types.md): All available field types
- [Complete association example](../assets/add_association_fields.py)
- [ValueObject example](../assets/add_value_object_field.py)
- [aggregate](../../aggregate/SKILL.md)
- [entity](../../entity/SKILL.md)
- [value-object](../../value-object/SKILL.md)
