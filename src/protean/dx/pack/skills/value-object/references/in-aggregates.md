# Value Objects in Aggregates

An aggregate holds a value object through a `ValueObject` field, builds new value objects in its methods, and replaces a value object whole to change it.

## Code

The complete implementation is in [assets/value_object_in_aggregate.py](../assets/value_object_in_aggregate.py).

## Walkthrough

### Basic Embedding

```python
from decimal import Decimal as D

from protean.exceptions import IncorrectUsageError


@domain.value_object
class Money:
    currency: String(max_length=3, default="USD")
    amount: Decimal(precision=19, scale=4, default=0)

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("Cannot add different currencies")
        return Money(currency=self.currency, amount=self.amount + other.amount)

    def subtract(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("Cannot subtract different currencies")
        return Money(currency=self.currency, amount=self.amount - other.amount)

    def multiply(self, factor: int) -> "Money":
        return Money(currency=self.currency, amount=self.amount * factor)


@domain.aggregate
class Order:
    """Order aggregate with Money value object."""
    order_number: String(required=True, identifier=True)
    total_amount = ValueObject(Money, required=True)
    status: String(default="pending")
```

The rest of this page reuses this `Money` class.

### Multiple Value Objects

An aggregate can hold several value objects, and the same value object type more than once, such as an `Order` with both `shipping_address = ValueObject(Address)` and `billing_address = ValueObject(Address)`. The rest of this page reuses this `Address`:

```python
@domain.value_object
class Address:
    street: String(required=True, max_length=100)
    city: String(required=True, max_length=50)
    state: String(required=True, max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(required=True, max_length=50)
```

### Value Objects in Aggregate Methods

```python
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
    line_items = HasMany(OrderLine)
    total_amount = ValueObject(Money, required=True)
    status: String(default="pending")

    def calculate_total(self) -> Money:
        """
        Calculate order total using value object operations.

        Demonstrates how aggregates work with value objects
        to implement domain rules.
        """
        if not self.line_items:
            return Money(currency="USD", amount=D("0"))

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

### Replacing Value Objects (Immutability)

```python
@domain.aggregate
class Order:
    shipping_address = ValueObject(Address, required=True)
    status: String(default="pending")

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

The aggregate method decides when a replacement is allowed.

## Common Patterns

The examples below reuse the `Money` and `Address` value objects defined above.

### Order with Line Items and Money

The `Order` that the rest of this page builds and tests, with the `OrderLine` entity from above:

```python
@domain.aggregate
class Order:
    order_number: String(required=True, identifier=True)
    customer_id: Identifier(required=True)  # Customer is another aggregate
    shipping_address = ValueObject(Address, required=True)
    total_amount = ValueObject(Money, required=True)
    line_items = HasMany(OrderLine)

    def calculate_total(self) -> Money:
        if not self.line_items:
            return Money(currency="USD", amount=D("0"))
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
            return Money(currency=self.price.currency, amount=D("10.00"))

        # Rate based on volume. Volume is a float; convert it before
        # mixing it with money, and round to cents.
        volume = D(str(self.dimensions.volume))
        rate = D("0.05")  # per cubic unit

        shipping_amount = (volume * rate).quantize(D("0.01"))
        return Money(
            currency=self.price.currency,
            amount=max(shipping_amount, D("5.00"))  # Minimum $5
        )
```

### Account with Balance and Transactions

```python
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

Creating an aggregate needs an initialized domain and an active domain context.

### Initialize with Complete Value Objects

```python
domain.init(traverse=False)

with domain.domain_context():
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
        total_amount=Money(currency="USD", amount=D("100.00"))
    )
```

### Initialize with Attributes

```python
with domain.domain_context():
    order = Order(
        order_number="ORD-002",
        customer_id="CUST-456",
        shipping_address_street="456 Oak Ave",
        shipping_address_city="New York",
        shipping_address_state="NY",
        shipping_address_postal_code="10001",
        shipping_address_country="USA",
        total_amount_currency="USD",
        total_amount_amount=D("200.00")
    )
```

Both approaches produce identical aggregates. Flattened attributes work one level deep: `shipping_address_city` sets `city` on the `shipping_address` value object. If a value object holds another value object, pass the inner one as an object.

## Testing Aggregates with Value Objects

```python
import pytest


def build_order() -> Order:
    return Order(
        order_number="ORD-001",
        customer_id="CUST-123",
        shipping_address=Address(
            street="123 Main St",
            city="Boston",
            state="MA",
            postal_code="02101",
            country="USA"
        ),
        total_amount=Money(currency="USD", amount=D("100.00"))
    )


def test_order_creation():
    order = build_order()

    assert order.total_amount.amount == D("100.00")
    assert order.shipping_address.city == "Boston"

def test_order_calculate_total():
    order = build_order()
    order.add_line_items(
        OrderLine(
            product_id="PROD-001",
            quantity=2,
            unit_price=Money(currency="USD", amount=D("50.00"))
        )
    )

    total = order.calculate_total()
    assert total.amount == D("100.00")
    assert total.currency == "USD"

def test_cannot_modify_value_object():
    order = build_order()

    with pytest.raises(IncorrectUsageError):
        order.total_amount.amount = D("200.00")

    # Correct way: replace entire value object
    order.total_amount = Money(currency="USD", amount=D("200.00"))
    assert order.total_amount.amount == D("200.00")
```

These tests run inside a domain context, which the test setup provides.

## Common Mistakes

**Missing required value objects** ❌
```python
# fragment
# If VO is required, don't allow None
@domain.aggregate
class Order:
    # Bad: Optional when it should be required
    total_amount = ValueObject(Money)

    # Good: Explicitly required
    total_amount = ValueObject(Money, required=True)
```

## Related

- [Value Objects in Entities](./in-entities.md): Using VOs in entities
- [Nested Value Objects](./nested-value-objects.md): Composition patterns
- [Value Objects with Methods](./with-methods.md): VO behavior
- [../aggregate/SKILL.md](../../aggregate/SKILL.md): Aggregate skill
