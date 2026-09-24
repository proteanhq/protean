# Common Mistakes When Adding Fields

This guide documents common anti-patterns and mistakes when adding fields to Protean domain elements.

## Overview

This document covers:
1. Field type selection mistakes
2. Validation strategy mistakes
3. Association field mistakes
4. Placement and organization mistakes

## Field Type Selection Mistakes

### Mistake 1: Using String for Numeric Values

**Problem**: Storing numbers as strings loses type safety and makes calculations difficult.

**Bad**:
```python
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
    price: Float(required=True, min_value=0.01)
    quantity: Integer(required=True, min_value=0)
    discount: Float(min_value=0.0, max_value=100.0, default=0.0)
```

**Why it matters**: Type safety, automatic validation, database optimization, calculation support.

---

### Mistake 2: Using Text for Short Strings

**Problem**: Text fields have no length limits and are less efficient for short values.

**Bad**:
```python
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

**Why it matters**: Database efficiency, validation, prevents abuse.

---

### Mistake 3: Using Simple Fields Instead of Value Objects

**Problem**: Related attributes scattered across fields instead of cohesive value object.

**Bad**:
```python
@domain.aggregate
class Order:
    total_amount: Float()
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
    amount: Float(required=True)
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

**Why it matters**: Cohesion, reusability, encapsulation, maintainability.

---

### Mistake 4: Wrong Field for Collections

**Problem**: Using HasMany for simple values or List for entities.

**Bad**:
```python
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

**Why it matters**: Performance, simplicity, proper relationship modeling.

## Validation Strategy Mistakes

### Mistake 5: Not Using Field-Level Validation

**Problem**: Manual validation in methods instead of built-in field parameters.

**Bad**:
```python
@domain.aggregate
class Product:
    price: Float(required=True)  # No validation!
    stock_count: Integer(default=0)  # No validation!

    def set_price(self, new_price: float):
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
@domain.aggregate
class Product:
    # Field-level validation automatically enforced
    price: Float(required=True, min_value=0.01, max_value=999999.99)
    stock_count: Integer(default=0, min_value=0)

    def set_price(self, new_price: float):
        self.price = new_price  # Field validates automatically

    def adjust_stock(self, delta: int):
        self.stock_count += delta  # Field validates automatically
```

**Why it matters**: DRY principle, automatic enforcement, consistency, less code.

---

### Mistake 6: Using Invariants for Single-Field Constraints

**Problem**: Invariants for simple field validations instead of field parameters.

**Bad**:
```python
@domain.aggregate
class Product:
    price: Float(required=True)
    name: String(required=True)

    @invariant.post  # Wrong! Use field parameter
    def price_must_be_positive(self):
        if self.price <= 0:
            raise ValidationError("Price must be positive")

    @invariant.post  # Wrong! Use field parameter
    def name_must_not_be_too_long(self):
        if len(self.name) > 200:
            raise ValidationError("Name too long")
```

**Good**:
```python
@domain.aggregate
class Product:
    # Field-level validation
    price: Float(required=True, min_value=0.01)
    name: String(required=True, max_length=200)

    # Invariants ONLY for cross-field business rules
    @invariant.post
    def discounted_price_must_be_positive(self):
        """Cross-field business rule."""
        if self.discount_percent > 0:
            final = self.price * (1 - self.discount_percent / 100)
            if final <= 0:
                raise ValidationError("Discount makes price negative")
```

**Why it matters**: Right tool for the job, clearer intent, automatic enforcement.

---

### Mistake 7: Missing Validation Entirely

**Problem**: No validation on fields that need constraints.

**Bad**:
```python
@domain.aggregate
class User:
    age: Integer()  # No min/max!
    email: String()  # No format validation!
    password: String()  # No length requirement!
```

**Good**:
```python
class EmailValidator:
    def __call__(self, value: str):
        if "@" not in value or value.startswith("@"):
            raise ValidationError("Invalid email")

@domain.aggregate
class User:
    age: Integer(required=True, min_value=13, max_value=150)
    email: String(required=True, max_length=254, validators=[EmailValidator()])
    password: String(required=True, min_length=8, max_length=100)
```

**Why it matters**: Data integrity, security, preventing invalid states.

## Association Field Mistakes

### Mistake 8: Manually Creating Auto-Generated Methods

**Problem**: Defining methods that Protean already generates for HasMany.

**Bad**:
```python
@domain.aggregate
class Order:
    line_items = HasMany("LineItem")

    # DON'T DO THIS! Already auto-generated
    def add_line_items(self, items):
        """Manual implementation."""
        if not isinstance(items, list):
            items = [items]
        self._line_items.extend(items)

    # DON'T DO THIS! Already auto-generated
    def remove_line_items(self, item):
        """Manual implementation."""
        self._line_items.remove(item)
```

**Good**:
```python
@domain.aggregate
class Order:
    line_items = HasMany("LineItem")
    # add_line_items(), remove_line_items() already exist!

    # Only create custom methods when you need ADDITIONAL logic
    def add_product(self, product_id: str, quantity: int, price: float):
        """Custom method with validation."""
        if quantity > 100:
            raise ValueError("Max 100 per product")

        # Use auto-generated helper
        item = LineItem(product_id=product_id, quantity=quantity, unit_price=price)
        self.add_line_items([item])
```

**Why it matters**: Don't fight the framework, less code to maintain, consistent API.

---

### Mistake 9: Forgetting part_of for Entities

**Problem**: Defining entity without associating with parent aggregate.

**Bad**:
```python
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

**Why it matters**: Entities must belong to aggregates, defines persistence boundary.

---

### Mistake 10: Wrong Association Type

**Problem**: Using Reference for same-aggregate relationships or HasMany for cross-aggregate.

**Bad**:
```python
@domain.aggregate
class Order:
    # Wrong! LineItem is part of Order aggregate
    line_items = Reference("LineItem")  # Should be HasMany

@domain.aggregate
class Order:
    # Wrong! Customer is separate aggregate
    customer = HasMany("Customer")  # Should be Reference
```

**Good**:
```python
@domain.aggregate
class Order:
    # Correct: HasMany for same-aggregate entities
    line_items = HasMany("LineItem")

    # Correct: Reference for cross-aggregate
    customer = Reference("Customer")

@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
```

**Why it matters**: Proper aggregate boundaries, correct relationship modeling.

## Placement and Organization Mistakes

### Mistake 11: Adding Fields to Wrong Element

**Problem**: Putting fields in the wrong aggregate, entity, or value object.

**Bad**:
```python
# Order details scattered
@domain.aggregate
class Customer:
    name: String(required=True)
    order_total: Float()  # Wrong! Belongs to Order
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
    customer = Reference("Customer")
    total = ValueObject(Money)
    status: String(choices=["draft", "placed", "shipped"])
    line_items = HasMany("LineItem")

@domain.entity(part_of="Order")
class LineItem:  # Correctly an entity
    product_id: String(required=True)
    quantity: Integer(required=True)
```

**Why it matters**: Proper boundaries, cohesion, transaction consistency.

---

### Mistake 12: Not Using Value Objects for Complex Data

**Problem**: Primitive fields for complex concepts that should be value objects.

**Bad**:
```python
@domain.aggregate
class Order:
    # Email as primitive string
    customer_email: String()  # No validation!

    # Money as primitives
    total_amount: Float()
    total_currency: String()  # Scattered

    # Address as primitives
    street: String()
    city: String()
    state: String()
    postal_code: String()  # Many related fields
```

**Good**:
```python
@domain.value_object
class Email:
    address: String(required=True, validators=[EmailValidator()])

@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

@domain.value_object
class Address:
    street: String(required=True, max_length=100)
    city: String(required=True, max_length=50)
    state: String(required=True, max_length=50)
    postal_code: String(required=True, max_length=20)

@domain.aggregate
class Order:
    customer_email = ValueObject(Email, required=True)
    total = ValueObject(Money, required=True)
    shipping_address = ValueObject(Address, required=True)
```

**Why it matters**: Encapsulation, reusability, validation, clarity.

## Field Configuration Mistakes

### Mistake 13: Not Setting required Explicitly

**Problem**: Relying on defaults instead of explicitly stating required/optional.

**Bad**:
```python
@domain.aggregate
class User:
    email: String()  # Is this required? Unclear
    name: String()  # Is this required? Unclear
```

**Good**:
```python
@domain.aggregate
class User:
    email: String(required=True)  # Explicit
    name: String(required=True)  # Explicit
    bio: String()  # Explicitly optional (required=False is default)
```

**Why it matters**: Clarity, prevents bugs, self-documenting.

---

### Mistake 14: Missing Default Values

**Problem**: Not providing defaults for optional fields that should have them.

**Bad**:
```python
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

**Why it matters**: Predictable behavior, fewer None checks, clearer intent.

---

### Mistake 15: Not Using choices for Enums

**Problem**: Free-form strings instead of constrained choices.

**Bad**:
```python
@domain.aggregate
class Order:
    status: String()  # Any value allowed! Typos possible
```

**Good**:
```python
@domain.aggregate
class Order:
    status: String(
        required=True,
        default="draft",
        choices=["draft", "placed", "shipped", "delivered", "cancelled"]
    )
```

**Why it matters**: Type safety, prevents typos, self-documenting.

## Testing and Debugging Mistakes

### Mistake 16: Not Testing Field Validation

**Problem**: Adding fields without verifying validation works.

**Bad**:
```python
# Add field and assume it works
price: Float(min_value=0.01)

# No tests!
```

**Good**:
```python
# Add field with validation
price: Float(required=True, min_value=0.01, max_value=999999.99)

# Write tests
def test_product_price_validation():
    # Test valid price
    product = Product(name="Widget", price=50.0)
    assert product.price == 50.0

    # Test invalid price (too low)
    with pytest.raises(ValidationError):
        Product(name="Widget", price=0.0)

    # Test invalid price (too high)
    with pytest.raises(ValidationError):
        Product(name="Widget", price=1000000.0)
```

**Why it matters**: Confidence, catches bugs early, documents behavior.

---

### Mistake 17: Inconsistent Field Naming

**Problem**: Inconsistent naming conventions across fields.

**Bad**:
```python
@domain.aggregate
class Order:
    customerID: String()  # camelCase
    order_number: String()  # snake_case
    OrderTotal: Float()  # PascalCase
    line_items = HasMany("LineItem")  # snake_case
```

**Good**:
```python
@domain.aggregate
class Order:
    customer_id: String()  # Consistent snake_case
    order_number: String()  # Consistent snake_case
    total = ValueObject(Money)  # Consistent snake_case
    line_items = HasMany("LineItem")  # Consistent snake_case
```

**Why it matters**: Readability, maintainability, Python conventions.

## Summary Checklist

Before adding a field, verify:

**Field Type**:
- [ ] Using correct type (String vs Text, Integer vs Float)
- [ ] Not using String for numeric values
- [ ] Using ValueObject for complex/related data

**Validation**:
- [ ] Using field-level validation for data type constraints
- [ ] Using invariants only for cross-field rules
- [ ] Custom validators for complex format validation

**Associations**:
- [ ] Using correct association type (HasOne, HasMany, ValueObject, Reference)
- [ ] Not manually creating auto-generated methods
- [ ] Entities have part_of specified

**Configuration**:
- [ ] Explicitly setting required=True/False
- [ ] Providing sensible defaults
- [ ] Using choices for enum-like fields
- [ ] Setting min/max values for numbers
- [ ] Setting length limits for strings

**Organization**:
- [ ] Field in correct element (aggregate, entity, value object)
- [ ] Related fields grouped in value objects
- [ ] Consistent naming conventions

## See Also

- [Field Types Guide](field-types.md) - Choosing the right field type
- [Validation Strategies](validation.md) - Validation approaches
- [Association Fields](associations.md) - Relationship patterns
- Complete examples in [assets/](../assets/)
