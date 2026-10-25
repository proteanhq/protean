# Value Objects in Entities

An entity holds value objects the same way an aggregate does, through `ValueObject` fields. The entity is reached through its parent aggregate.

## Code

The complete implementation is in [assets/value_object_in_entity.py](../assets/value_object_in_entity.py).

## Walkthrough

### Basic Embedding in Entity

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

    def multiply(self, factor: int) -> "Money":
        return Money(currency=self.currency, amount=self.amount * factor)


@domain.entity(part_of="Order")
class LineItem:
    """LineItem entity with Money value object."""
    product_id: String(required=True)
    product_name: String(required=True)
    quantity: Integer(required=True, min_value=1)
    unit_price = ValueObject(Money, required=True)

    @property
    def line_total(self) -> Money:
        """Calculate line total using Money's multiply method."""
        return self.unit_price.multiply(self.quantity)
```

The rest of this page reuses this `Money` class.

### Multiple Value Objects in Entity

```python
@domain.value_object
class Dimensions:
    length: Float(required=True)
    width: Float(required=True)
    height: Float(required=True)
    weight: Float(required=True)

    @property
    def volume(self) -> float:
        return self.length * self.width * self.height


@domain.entity(part_of="Order")
class LineItem:
    """Entity with multiple value objects."""
    product_id: String(required=True)
    product_name: String(required=True)
    quantity: Integer(required=True, min_value=1)

    # Multiple value objects
    unit_price = ValueObject(Money, required=True)
    dimensions = ValueObject(Dimensions)

    @property
    def line_total(self) -> Money:
        return self.unit_price.multiply(self.quantity)

    @property
    def total_volume(self) -> float:
        if self.dimensions:
            return self.dimensions.volume * self.quantity
        return 0.0
```

### Entity in Aggregate Context

```python
@domain.aggregate
class Order:
    """Order aggregate containing LineItem entities."""
    order_number: String(required=True, identifier=True)
    customer_id: Identifier(required=True)  # Customer is another aggregate
    line_items = HasMany(LineItem)

    def total(self) -> Money:
        """Calculate order total from line items."""
        if not self.line_items:
            return Money(currency="USD", amount=D("0"))

        total = self.line_items[0].line_total
        for item in self.line_items[1:]:
            total = total.add(item.line_total)

        return total
```

## Common Patterns

### Invoice Lines with Discounts

```python
@domain.entity(part_of="Invoice")
class InvoiceLine:
    """Invoice line with price and optional discount."""
    description: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price = ValueObject(Money, required=True)
    discount = ValueObject(Money)  # Optional

    @property
    def subtotal(self) -> Money:
        """Calculate subtotal before discount."""
        return self.unit_price.multiply(self.quantity)

    @property
    def total(self) -> Money:
        """Calculate total after discount."""
        subtotal = self.subtotal
        if self.discount:
            if subtotal.currency != self.discount.currency:
                raise ValueError("Discount currency must match")
            return Money(
                currency=subtotal.currency,
                amount=subtotal.amount - self.discount.amount
            )
        return subtotal


@domain.aggregate
class Invoice:
    invoice_number: String(required=True, identifier=True)
    lines = HasMany(InvoiceLine)

    def total(self) -> Money:
        if not self.lines:
            return Money(currency="USD", amount=D("0"))

        total = self.lines[0].total
        for line in self.lines[1:]:
            total = total.add(line.total)

        return total
```

### Inventory with Location

```python
@domain.value_object
class WarehouseLocation:
    """Location within warehouse."""
    aisle: String(required=True, max_length=10)
    shelf: String(required=True, max_length=10)
    bin: String(required=True, max_length=10)

    @property
    def full_location(self) -> str:
        return f"{self.aisle}-{self.shelf}-{self.bin}"


@domain.entity(part_of="Inventory")
class InventoryItem:
    """Item in inventory with location."""
    sku: String(required=True, max_length=50)
    quantity: Integer(required=True, min_value=0)
    location = ValueObject(WarehouseLocation, required=True)

    def move_to(self, new_location: WarehouseLocation):
        """Move item to new warehouse location."""
        self.location = new_location


@domain.aggregate
class Inventory:
    warehouse_id: String(required=True, identifier=True)
    items = HasMany(InventoryItem)

    def find_item_location(self, sku: str) -> WarehouseLocation:
        """Find where an item is located."""
        for item in self.items:
            if item.sku == sku:
                return item.location
        raise ValueError(f"SKU {sku} not found")
```

## Initialization Patterns

Creating an entity or aggregate needs an initialized domain and an active domain context.

### Initialize Entity with Value Object

```python
domain.init(traverse=False)

with domain.domain_context():
    # With complete value object
    line_item = LineItem(
        product_id="PROD-001",
        product_name="Laptop",
        quantity=2,
        unit_price=Money(currency="USD", amount=D("1200.00"))
    )

    # By attributes (one level deep)
    line_item = LineItem(
        product_id="PROD-001",
        product_name="Laptop",
        quantity=2,
        unit_price_currency="USD",
        unit_price_amount=D("1200.00")
    )
```

### Add Entity to Aggregate

```python
with domain.domain_context():
    order = Order(order_number="ORD-001", customer_id="CUST-123")

    # Add with complete VO
    order.add_line_items(
        LineItem(
            product_id="PROD-001",
            product_name="Laptop",
            quantity=1,
            unit_price=Money(currency="USD", amount=D("1200.00"))
        )
    )
```

## Replacing Value Objects in Entities

```python
with domain.domain_context():
    # Cannot modify value object
    try:
        line_item.unit_price.amount = D("1000.00")
    except IncorrectUsageError:
        print("Replace the value object instead")

    # Replace entire value object
    line_item.unit_price = Money(currency="USD", amount=D("1000.00"))
```

An entity method can do the replacement too, as `InventoryItem.move_to` does above.

## Testing Entities with Value Objects

```python
import pytest


def test_line_item_total_calculation():
    item = LineItem(
        product_id="PROD-001",
        product_name="Laptop",
        quantity=3,
        unit_price=Money(currency="USD", amount=D("50.00"))
    )

    total = item.line_total
    assert total.amount == D("150.00")
    assert total.currency == "USD"
```

This test runs inside a domain context, which the test setup provides.

## Common Mistakes

**Accessing entities directly** ❌
```python
# fragment
# Bad: loading a line item on its own, outside its Order
line_item = domain.repository_for(LineItem).get(item_id)
```

```python
# Good: Through aggregate
with domain.domain_context():
    repo = domain.repository_for(Order)
    repo.add(order)

    order = repo.get("ORD-001")
    line_item = order.line_items[0]
```

## Related

- [Value Objects in Aggregates](./in-aggregates.md): Similar patterns in aggregates
- [Value Objects with Methods](./with-methods.md): VO behavior
- [Nested Value Objects](./nested-value-objects.md): Composition
- [../entity/SKILL.md](../../entity/SKILL.md): Entity skill
