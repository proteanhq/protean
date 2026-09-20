# Value Objects in Entities

Entities can contain value objects just like aggregates. This reference shows how to embed value objects in entities, how entities with value objects work within aggregates, and patterns for using value objects at the entity level.

## Overview

Value objects in entities:
- Represent complex attributes of entities
- Work the same way as in aggregates
- Are accessed through the parent aggregate
- Maintain immutability at entity level
- Simplify entity design and validation

## Code

The complete implementation is in [assets/value_object_in_entity.py](../assets/value_object_in_entity.py).

Key highlights:
- Entities with value objects as part of aggregates
- Multiple value objects in entities
- Entity methods using value objects
- Real-world line item scenarios

## Walkthrough

### Basic Embedding in Entity

```python
@domain.value_object
class Money:
    currency: String(max_length=3, default="USD")
    amount: Float(default=0.0)


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

The entity:
- Uses `ValueObject` field just like aggregates
- Value object encapsulates price validation
- Entity methods return value objects
- Clean separation of concerns

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

Benefits:
- Entity models complex domain concepts
- Each value object has focused responsibility
- Entity remains readable and maintainable

### Entity in Aggregate Context

```python
@domain.aggregate
class Order:
    """Order aggregate containing LineItem entities."""
    order_number: String(required=True, identifier=True)
    customer_id: String(required=True)
    line_items = HasMany(LineItem)

    def total(self) -> Money:
        """Calculate order total from line items."""
        if not self.line_items:
            return Money(currency="USD", amount=0.0)

        total = self.line_items[0].line_total
        for item in self.line_items[1:]:
            total = total.add(item.line_total)

        return total
```

The complete picture:
1. LineItem entities contain Money value objects
2. Order aggregate contains LineItem entities
3. Aggregate methods work with entity value objects
4. Clean flow of behavior through layers

## Common Patterns

### Order Lines with Pricing

```python
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Float(required=True)

    def multiply(self, factor: float) -> "Money":
        return Money(currency=self.currency, amount=self.amount * factor)


@domain.entity(part_of="Order")
class OrderLine:
    product_id: String(required=True)
    product_name: String(required=True)
    quantity: Integer(required=True, min_value=1)
    unit_price = ValueObject(Money, required=True)

    @property
    def line_total(self) -> Money:
        return self.unit_price.multiply(self.quantity)


@domain.aggregate
class Order:
    order_number: String(required=True, identifier=True)
    line_items = HasMany(OrderLine)

    def add_item(self, product_id: str, name: str, quantity: int, price: Money):
        """Add line item to order."""
        self.add_line_items(
            OrderLine(
                product_id=product_id,
                product_name=name,
                quantity=quantity,
                unit_price=price
            )
        )
```

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
            return Money(currency="USD", amount=0.0)

        total = self.lines[0].total
        for line in self.lines[1:]:
            total = total.add(line.total)

        return total
```

### Shipping Items with Dimensions

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


@domain.entity(part_of="Shipment")
class ShipmentItem:
    """Item in shipment with physical dimensions."""
    tracking_number: String(required=True)
    product_id: String(required=True)
    quantity: Integer(required=True, min_value=1)
    dimensions = ValueObject(Dimensions, required=True)

    @property
    def total_volume(self) -> float:
        return self.dimensions.volume * self.quantity

    @property
    def total_weight(self) -> float:
        return self.dimensions.weight * self.quantity


@domain.aggregate
class Shipment:
    shipment_id: String(required=True, identifier=True)
    items = HasMany(ShipmentItem)

    def total_volume(self) -> float:
        """Calculate total volume of all items."""
        return sum(item.total_volume for item in self.items)

    def total_weight(self) -> float:
        """Calculate total weight of all items."""
        return sum(item.total_weight for item in self.items)
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

### Initialize Entity with Value Object

```python
# With complete value object
line_item = LineItem(
    product_id="PROD-001",
    product_name="Laptop",
    quantity=2,
    unit_price=Money(currency="USD", amount=1200.0)
)

# By attributes
line_item = LineItem(
    product_id="PROD-001",
    product_name="Laptop",
    quantity=2,
    unit_price_currency="USD",
    unit_price_amount=1200.0
)
```

### Add Entity to Aggregate

```python
order = Order(order_number="ORD-001", customer_id="CUST-123")

# Add with complete VO
order.add_line_items(
    LineItem(
        product_id="PROD-001",
        product_name="Laptop",
        quantity=1,
        unit_price=Money(currency="USD", amount=1200.0)
    )
)
```

## Accessing Value Objects in Entities

```python
order = Order(...)

# Access entity
line_item = order.line_items[0]

# Access VO in entity
print(line_item.unit_price.currency)
print(line_item.unit_price.amount)

# Use entity methods that return VOs
total = line_item.line_total
print(f"Line total: {total.currency} {total.amount}")

# Aggregate methods using entity VOs
order_total = order.total()
print(f"Order total: {order_total.currency} {order_total.amount}")
```

## Replacing Value Objects in Entities

```python
# Cannot modify value object
line_item.unit_price.amount = 1000.0  # Raises IncorrectUsageError

# Replace entire value object
line_item.unit_price = Money(currency="USD", amount=1000.0)

# Or through entity method
def update_price(self, new_price: Money):
    """Update line item price."""
    self.unit_price = new_price
```

## Testing Entities with Value Objects

```python
def test_line_item_with_money():
    item = LineItem(
        product_id="PROD-001",
        product_name="Laptop",
        quantity=2,
        unit_price=Money(currency="USD", amount=100.0)
    )

    assert item.unit_price.amount == 100.0
    assert item.unit_price.currency == "USD"

def test_line_item_total_calculation():
    item = LineItem(
        product_id="PROD-001",
        product_name="Laptop",
        quantity=3,
        unit_price=Money(currency="USD", amount=50.0)
    )

    total = item.line_total
    assert total.amount == 150.0
    assert total.currency == "USD"

def test_entity_value_object_immutability():
    item = LineItem(...)

    with pytest.raises(IncorrectUsageError):
        item.unit_price.amount = 200.0

    # Correct way
    item.unit_price = Money(currency="USD", amount=200.0)
    assert item.unit_price.amount == 200.0
```

## Best Practices

1. **Use VOs for complex entity attributes** - Not just primitives
2. **Entity methods return VOs** - Makes operations explicit
3. **Access entities through aggregates** - Never directly
4. **VOs work same in entities as aggregates** - Consistent patterns
5. **Replace, don't modify** - Honor immutability
6. **Test entity VO interactions** - Ensure behavior is correct
7. **Document VO usage in entities** - Help future developers

## Common Mistakes

**Exposing primitives instead of VOs** ❌
```python
@domain.entity(part_of="Order")
class LineItem:
    # Bad: Primitives
    price_amount: Float()
    price_currency: String()

    # Good: Value object
    unit_price = ValueObject(Money)
```

**Trying to modify entity VOs** ❌
```python
# Won't work
line_item.unit_price.amount = 100

# Correct
line_item.unit_price = Money(currency="USD", amount=100)
```

**Not using VO methods** ❌
```python
# Bad: Manual calculation
def line_total(self):
    return self.unit_price.amount * self.quantity

# Good: Using VO method
def line_total(self):
    return self.unit_price.multiply(self.quantity)
```

**Accessing entities directly** ❌
```python
# Bad: Direct entity access
line_item = repository.get_line_item(item_id)

# Good: Through aggregate
order = repository.get_order(order_id)
line_item = order.line_items[0]
```

## Related

- [Value Objects in Aggregates](./in-aggregates.md) - Similar patterns in aggregates
- [Value Objects with Methods](./with-methods.md) - VO behavior
- [Nested Value Objects](./nested-value-objects.md) - Composition
- [../entity/SKILL.md](../../entity/SKILL.md) - Entity skill
