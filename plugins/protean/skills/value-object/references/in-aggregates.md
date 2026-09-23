# Value Objects in Aggregates

Value objects are primarily used within aggregates and entities to represent complex attributes. This reference shows how to effectively embed and use value objects in aggregates, including patterns, best practices, and real-world scenarios.

## Overview

Value objects in aggregates:
- Represent descriptive attributes of the aggregate
- Encapsulate validation and business logic
- Make the domain model more expressive
- Ensure data integrity through immutability
- Simplify persistence and retrieval

## Code

The complete implementation is in [assets/value_object_in_aggregate.py](../assets/value_object_in_aggregate.py).

Key highlights:
- Multiple value objects in single aggregate
- Value objects in aggregate methods
- Business logic using value objects
- Complete real-world order scenario

## Walkthrough

### Basic Embedding

```python
@domain.value_object
class Money:
    currency: String(max_length=3, default="USD")
    amount: Integer(default=0)


@domain.aggregate
class Order:
    """Order aggregate with Money value object."""
    order_number: String(required=True, identifier=True)
    total_amount = ValueObject(Money, required=True)
    status: String(default="pending")
```

The aggregate:
- Uses `ValueObject` field to embed Money
- Money handles its own validation
- Total amount is always valid currency + amount combination

### Multiple Value Objects

```python
@domain.aggregate
class Order:
    """Order with multiple value objects."""
    order_number: String(required=True, identifier=True)

    # Multiple different value object types
    shipping_address = ValueObject(Address, required=True)
    billing_address = ValueObject(Address)
    total_amount = ValueObject(Money, required=True)
    discount = ValueObject(Money)

    status: String(default="pending")
```

Benefits:
- Each value object encapsulates its own logic
- Aggregate remains clean and focused
- Type safety for complex attributes
- Consistent validation across all instances

### Value Objects in Aggregate Methods

```python
@domain.aggregate
class Order:
    line_items = HasMany(OrderLine)
    total_amount = ValueObject(Money, required=True)

    def calculate_total(self) -> Money:
        """
        Calculate order total using value object operations.

        Demonstrates how aggregates work with value objects
        to implement domain rules.
        """
        if not self.line_items:
            return Money(currency="USD", amount=0)

        total = self.line_items[0].line_total
        for item in self.line_items[1:]:
            total = total.add(item.line_total)

        return total

    def confirm_order(self):
        """Confirm order and update total."""
        if self.status != "pending":
            raise ValueError(f"Cannot confirm order in status: {self.status}")

        # Use value object in business logic
        self.total_amount = self.calculate_total()
        self.status = "confirmed"
```

Patterns:
- Methods return value objects
- Value object methods (like `add`) used in aggregate logic
- Aggregate orchestrates value object operations
- Business rules implemented clearly

### Replacing Value Objects (Immutability)

```python
@domain.aggregate
class Order:
    shipping_address = ValueObject(Address, required=True)

    def update_shipping_address(self, new_address: Address):
        """
        Update shipping address.

        Business rule: Cannot update shipped orders.
        Value objects are replaced, not modified.
        """
        if self.status in ["shipped", "delivered"]:
            raise ValueError("Cannot update shipped orders")

        # Replace entire value object (immutability)
        self.shipping_address = new_address
```

Key points:
- Value objects cannot be modified
- Always replace with new instance
- Business rules protect when replacement is allowed
- Clean, explicit state changes

## Common Patterns

### Order with Line Items and Money

Complete e-commerce order scenario:

```python
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Integer(required=True)

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("Cannot add different currencies")
        return Money(currency=self.currency, amount=self.amount + other.amount)


@domain.entity(part_of="Order")
class OrderLine:
    product_id: String(required=True)
    quantity: Integer(required=True, min_value=1)
    unit_price = ValueObject(Money, required=True)

    @property
    def line_total(self) -> Money:
        return self.unit_price.multiply(self.quantity)


@domain.aggregate
class Order:
    order_number: String(required=True, identifier=True)
    customer_id: String(required=True)
    shipping_address = ValueObject(Address, required=True)
    total_amount = ValueObject(Money, required=True)
    line_items = HasMany(OrderLine)

    def calculate_total(self) -> Money:
        if not self.line_items:
            return Money(currency="USD", amount=0)
        total = self.line_items[0].line_total
        for item in self.line_items[1:]:
            total = total.add(item.line_total)
        return total
```

### Customer with Contact Information

```python
@domain.value_object
class Email:
    address: String(max_length=254, required=True)


@domain.value_object
class PhoneNumber:
    country_code: String(max_length=5, required=True)
    number: String(max_length=15, required=True)

    @property
    def full_number(self) -> str:
        return f"{self.country_code}{self.number}"


@domain.value_object
class Address:
    street: String(required=True, max_length=100)
    city: String(required=True, max_length=50)
    state: String(required=True, max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(required=True, max_length=50)


@domain.aggregate
class Customer:
    customer_id: String(required=True, identifier=True)
    name: String(required=True, max_length=100)

    # Multiple value objects for different purposes
    email = ValueObject(Email, required=True)
    phone = ValueObject(PhoneNumber)
    shipping_address = ValueObject(Address, required=True)
    billing_address = ValueObject(Address)

    def update_email(self, new_email: Email):
        """Update customer email with validation."""
        # Email VO ensures validation
        self.email = new_email

    def use_shipping_for_billing(self):
        """Set billing address same as shipping."""
        self.billing_address = self.shipping_address
```

### Product with Dimensions and Price

```python
@domain.value_object
class Dimensions:
    length: Float(required=True, min_value=0)
    width: Float(required=True, min_value=0)
    height: Float(required=True, min_value=0)
    weight: Float(required=True, min_value=0)

    @property
    def volume(self) -> float:
        return self.length * self.width * self.height


@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Float(required=True, min_value=0)


@domain.aggregate
class Product:
    sku: String(required=True, max_length=50, identifier=True)
    name: String(required=True, max_length=200)
    description: String(max_length=2000)

    # Value objects for complex attributes
    price = ValueObject(Money, required=True)
    dimensions = ValueObject(Dimensions)

    def calculate_shipping_cost(self) -> Money:
        """Calculate shipping based on dimensions."""
        if not self.dimensions:
            # Default flat rate
            return Money(currency=self.price.currency, amount=10.0)

        # Rate based on volume
        volume = self.dimensions.volume
        rate = 0.05  # per cubic unit

        shipping_amount = volume * rate
        return Money(
            currency=self.price.currency,
            amount=max(shipping_amount, 5.0)  # Minimum $5
        )
```

### Account with Balance and Transactions

```python
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Float(required=True)

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("Currency mismatch")
        return Money(currency=self.currency, amount=self.amount + other.amount)

    def subtract(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("Currency mismatch")
        return Money(currency=self.currency, amount=self.amount - other.amount)


@domain.aggregate
class Account:
    account_number: String(required=True, identifier=True)
    account_type: String(required=True)
    balance = ValueObject(Money, required=True)

    def deposit(self, amount: Money):
        """Add funds to account."""
        self.balance = self.balance.add(amount)

    def withdraw(self, amount: Money):
        """Remove funds from account."""
        # Business rule: no overdraft
        new_balance = self.balance.subtract(amount)
        if new_balance.amount < 0:
            raise ValueError("Insufficient funds")
        self.balance = new_balance

    def transfer_to(self, other_account: "Account", amount: Money):
        """Transfer funds to another account."""
        self.withdraw(amount)
        other_account.deposit(amount)
```

## Initialization Patterns

### Initialize with Complete Value Objects

```python
order = Order(
    order_number="ORD-001",
    customer_id="CUST-123",
    shipping_address=Address(
        street="123 Main St",
        city="Boston",
        state="MA",
        postal_code="02101",
        country="USA"
    ),
    total_amount=Money(currency="USD", amount=100)
)
```

### Initialize with Attributes

```python
order = Order(
    order_number="ORD-002",
    customer_id="CUST-456",
    shipping_address_street="456 Oak Ave",
    shipping_address_city="New York",
    shipping_address_state="NY",
    shipping_address_postal_code="10001",
    shipping_address_country="USA",
    total_amount_currency="USD",
    total_amount_amount=200
)
```

Both approaches produce identical aggregates.

## Accessing Value Object Attributes

```python
order = Order(...)

# Access value object
print(order.total_amount.currency)
print(order.total_amount.amount)

# Access nested value object
print(order.shipping_address.street)
print(order.shipping_address.city)

# Use in methods
if order.total_amount.amount > 1000:
    apply_bulk_discount(order)
```

## Testing Aggregates with Value Objects

```python
def test_order_creation():
    order = Order(
        order_number="ORD-001",
        customer_id="CUST-123",
        shipping_address=Address(...),
        total_amount=Money(currency="USD", amount=100)
    )

    assert order.total_amount.amount == 100
    assert order.shipping_address.city == "Boston"

def test_order_calculate_total():
    order = Order(...)
    order.add_line_items(
        OrderLine(
            product_id="PROD-001",
            quantity=2,
            unit_price=Money(currency="USD", amount=50)
        )
    )

    total = order.calculate_total()
    assert total.amount == 100
    assert total.currency == "USD"

def test_cannot_modify_value_object():
    order = Order(...)

    with pytest.raises(IncorrectUsageError):
        order.total_amount.amount = 200

    # Correct way: replace entire value object
    order.total_amount = Money(currency="USD", amount=200)
    assert order.total_amount.amount == 200
```

## Best Practices

1. **Use value objects for complex attributes** - Don't flatten to primitives
2. **Keep aggregates focused** - VOs handle attribute validation
3. **Return value objects from methods** - Makes return types explicit
4. **Use VO methods in aggregate logic** - Leverage VO behavior
5. **Replace, don't modify** - Honor immutability
6. **Validate with business rules** - Control when VOs can be replaced
7. **Initialize clearly** - Choose object or attribute initialization consistently

## Common Mistakes

**Flattening value objects** ❌
```python
@domain.aggregate
class Order:
    # Bad: Flattening Money to primitives
    amount: Float()
    currency: String()

    # Good: Using Money value object
    total = ValueObject(Money)
```

**Trying to modify value objects** ❌
```python
# Won't work - value objects are immutable
order.total_amount.amount = 200

# Correct - replace entire value object
order.total_amount = Money(currency="USD", amount=200)
```

**Not leveraging VO behavior** ❌
```python
# Bad: Reimplementing VO logic in aggregate
def calculate_total(self):
    total_amount = 0
    for item in self.line_items:
        total_amount += item.unit_price.amount * item.quantity
    return total_amount

# Good: Using VO methods
def calculate_total(self):
    total = self.line_items[0].line_total
    for item in self.line_items[1:]:
        total = total.add(item.line_total)
    return total
```

**Missing required value objects** ❌
```python
# If VO is required, don't allow None
@domain.aggregate
class Order:
    # Bad: Optional when it should be required
    total_amount = ValueObject(Money)

    # Good: Explicitly required
    total_amount = ValueObject(Money, required=True)
```

## Related

- [Value Objects in Entities](./in-entities.md) - Using VOs in entities
- [Nested Value Objects](./nested-value-objects.md) - Composition patterns
- [Value Objects with Methods](./with-methods.md) - VO behavior
- [../aggregate/SKILL.md](../../aggregate/SKILL.md) - Aggregate skill
