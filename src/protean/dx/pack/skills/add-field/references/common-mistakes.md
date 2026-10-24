# Common Mistakes When Adding Fields

## Field Type Selection Mistakes

### Mistake 1: Using String for Numeric Values

**Problem**: Storing numbers as strings loses type safety and makes calculations difficult.

**Bad**:
```python
# fragment
@domain.aggregate
class Product:
    price: String()  # Wrong type!
    quantity: String()  # Wrong type!
    discount: String()  # Wrong type!
```

**Good**:
```python
@domain.aggregate
class Product:
    price: Decimal(required=True, precision=19, scale=4, min_value=0.01)
    quantity: Integer(required=True, min_value=0)
    discount: Float(min_value=0.0, max_value=100.0, default=0.0)
```

### Mistake 2: Using Text for Short Strings

**Problem**: Text fields have no length limits and are less efficient for short values.

**Bad**:
```python
# fragment
@domain.aggregate
class User:
    username: Text()  # Too permissive!
    status: Text()  # Too permissive!
```

**Good**:
```python
@domain.aggregate
class User:
    username: String(required=True, max_length=50, min_length=3)
    status: String(max_length=20, choices=["active", "inactive", "banned"])
```

### Mistake 3: Using Simple Fields Instead of Value Objects

**Problem**: Related attributes scattered across fields instead of cohesive value object.

**Bad**:
```python
# fragment
@domain.aggregate
class Order:
    total_amount: Decimal(precision=19, scale=4)
    total_currency: String()  # Related but separate

    shipping_street: String()
    shipping_city: String()
    shipping_state: String()
    shipping_postal_code: String()  # Many related fields
```

**Good**:
```python
@domain.value_object
class Money:
    amount: Decimal(required=True, precision=19, scale=4)
    currency: String(max_length=3, default="USD")

@domain.value_object
class Address:
    street: String(required=True, max_length=100)
    city: String(required=True, max_length=50)
    state: String(required=True, max_length=50)
    postal_code: String(required=True, max_length=20)

@domain.aggregate
class Order:
    total = ValueObject(Money)  # Cohesive
    shipping_address = ValueObject(Address)  # Cohesive
```

### Mistake 4: Wrong Field for Collections

**Problem**: Using HasMany for simple values or List for entities.

**Bad**:
```python
# fragment
# Using HasMany for simple strings
@domain.entity(part_of="Product")
class Tag:
    name: String(required=True)

@domain.aggregate
class Product:
    tags = HasMany("Tag")  # Overkill for strings!

# Using List for entities
@domain.aggregate
class Order:
    line_items: List()  # Wrong! Entities need HasMany
```

**Good**:
```python
@domain.aggregate
class Product:
    tags: List(content_type=String)  # Simple list for strings

@domain.aggregate
class Order:
    line_items = HasMany("LineItem")  # HasMany for entities
```

## Validation Strategy Mistakes

### Mistake 5: Not Using Field-Level Validation

**Problem**: Manual validation in methods instead of built-in field parameters.

**Bad**:
```python
# fragment
@domain.aggregate
class Product:
    price: Decimal(required=True, precision=19, scale=4)  # No validation!
    stock_count: Integer(default=0)  # No validation!

    def set_price(self, new_price: D):
        # Manual validation repeated everywhere
        if new_price <= 0:
            raise ValueError("Price must be positive")
        if new_price > 999999.99:
            raise ValueError("Price too high")
        self.price = new_price

    def adjust_stock(self, delta: int):
        # Manual validation repeated
        new_stock = self.stock_count + delta
        if new_stock < 0:
            raise ValueError("Stock cannot be negative")
        self.stock_count = new_stock
```

**Good**:
```python
from decimal import Decimal as D

@domain.aggregate
class Product:
    # Field-level validation automatically enforced
    price: Decimal(required=True, precision=19, scale=4, min_value=0.01, max_value=999999.99)
    stock_count: Integer(default=0, min_value=0)

    def set_price(self, new_price: D):
        self.price = new_price  # Field validates automatically

    def adjust_stock(self, delta: int):
        self.stock_count += delta  # Field validates automatically
```

### Mistake 6: Using Invariants for Single-Field Constraints

**Problem**: Invariants for simple field validations instead of field parameters.

**Bad**:
```python
# fragment
from protean.exceptions import ValidationError

@domain.aggregate
class Product:
    price: Decimal(required=True, precision=19, scale=4)
    name: String(required=True)

    @invariant.post  # Wrong! Use field parameter
    def price_must_be_positive(self):
        if self.price <= 0:
            raise ValidationError({"price": ["Price must be positive"]})

    @invariant.post  # Wrong! Use field parameter
    def name_must_not_be_too_long(self):
        if len(self.name) > 200:
            raise ValidationError({"name": ["Name too long"]})
```

**Good**:
```python
from protean.exceptions import ValidationError

@domain.aggregate
class Product:
    # Field-level validation
    price: Decimal(required=True, precision=19, scale=4, min_value=0.01)
    sale_price: Decimal(precision=19, scale=4, min_value=0.01)
    name: String(required=True, max_length=200)

    # Invariants ONLY for cross-field business rules
    @invariant.post
    def sale_price_must_not_exceed_price(self):
        """Cross-field business rule."""
        if self.sale_price is not None and self.sale_price > self.price:
            raise ValidationError(
                {"_entity": ["Sale price cannot be higher than the price"]}
            )
```

## Association Field Mistakes

### Mistake 7: Forgetting part_of for Entities

**Problem**: Defining entity without associating with parent aggregate.

**Bad**:
```python
# fragment
@domain.entity  # ERROR! Missing part_of
class LineItem:
    product_id: String(required=True)
    quantity: Integer(required=True)
```

**Good**:
```python
@domain.entity(part_of="Order")  # Correct!
class LineItem:
    product_id: String(required=True)
    quantity: Integer(required=True)
```

### Mistake 8: Wrong Association Type

**Problem**: Using Reference for same-aggregate relationships, or an association field
(Reference, HasOne, HasMany) to point at another aggregate.

**Bad**:
```python
# fragment
@domain.aggregate
class Order:
    # Wrong! LineItem is part of Order aggregate
    line_items = Reference("LineItem")  # Should be HasMany

@domain.aggregate
class Order:
    # Wrong! Customer is separate aggregate
    customer = Reference("Customer")  # Should be an Identifier holding its id
    # protean check reports this as CROSS_AGGREGATE_REFERENCE
```

**Good**:
```python
@domain.aggregate
class Order:
    # Correct: HasMany for same-aggregate entities
    line_items = HasMany("LineItem")

    # Correct: Identifier holding the other aggregate's id
    customer_id = Identifier(required=True)

@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
```

Use `Reference` only on an entity, to point back at its parent (the aggregate root, or the
parent entity when nested). `HasMany` and `HasOne` add that field for you.

## Placement and Organization Mistakes

### Mistake 9: Adding Fields to Wrong Element

**Problem**: Putting fields in the wrong aggregate, entity, or value object.

**Bad**:
```python
# fragment
# Order details scattered
@domain.aggregate
class Customer:
    name: String(required=True)
    order_total: Decimal(precision=19, scale=4)  # Wrong! Belongs to Order
    order_status: String()  # Wrong! Belongs to Order

# Aggregate for data that should be entity
@domain.aggregate
class LineItem:  # Should be entity!
    product_id: String(required=True)
    quantity: Integer(required=True)
```

**Good**:
```python
@domain.aggregate
class Customer:
    name: String(required=True)
    # Order data belongs in Order aggregate

@domain.aggregate
class Order:
    customer_id = Identifier(required=True)  # Holds the Customer's id
    total = ValueObject(Money)
    status: String(choices=["draft", "placed", "shipped"])
    line_items = HasMany("LineItem")

@domain.entity(part_of="Order")
class LineItem:  # Correctly an entity
    product_id: String(required=True)
    quantity: Integer(required=True)
```

## Field Configuration Mistakes

### Mistake 10: Missing Default Values

**Problem**: Not providing defaults for optional fields that should have them.

**Bad**:
```python
# fragment
@domain.aggregate
class Post:
    title: String(required=True)
    view_count: Integer()  # No default, will be None
    status: String()  # No default, will be None
    is_published: Boolean()  # No default, will be None
```

**Good**:
```python
@domain.aggregate
class Post:
    title: String(required=True)
    view_count: Integer(default=0)  # Clear default
    status: String(default="draft")  # Clear default
    is_published: Boolean(default=False)  # Clear default
```

## See Also

- [Field Types Guide](field-types.md): Choosing the right field type
- [Validation Strategies](validation.md): Validation approaches
- [Association Fields](associations.md): Relationship patterns
- Complete examples in [assets/](../assets/)
