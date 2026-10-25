# Command Anti-Patterns

The examples below use these aggregates and value object:

```python
@domain.aggregate
class Order:
    customer_id: String(required=True)
    status: String(default="DRAFT")

    def place(self):
        self.status = "PLACED"

@domain.aggregate
class Inventory:
    product_id: String(required=True)

@domain.aggregate
class Product:
    name: String(required=True)

@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")
```

## 1. Using Past-Tense Verbs Instead of Imperative

### Wrong

```python
@domain.command(part_of="Order")
class OrderPlaced:  # Past-tense - this is an EVENT, not a command!
    order_id: Identifier(required=True)
```

### Correct

```python
@domain.command(part_of="Order")
class PlaceOrder:  # Imperative - describes the intent to act
    order_id: Identifier(required=True)
```

## 2. Not Associating Commands with Aggregates

### Wrong

```python
# fragment
@domain.command  # Missing part_of parameter!
class PlaceOrder:
    order_id: Identifier(required=True)
```

### Correct

```python
@domain.command(part_of="Order")  # Always specify which aggregate
class PlaceOrder:
    order_id: Identifier(required=True)
```

The decorator raises `IncorrectUsageError` without `part_of`.

## 3. Including Entities in Commands

### Wrong

```python
# fragment
@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
    quantity: Integer(required=True)

@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    items = HasMany(LineItem)  # Wrong! Can't include entities
```

### Correct

```python
@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    items: List()  # Serialize entity data as dictionaries
    # Or use value objects
    total = ValueObject(Money)
```

## 4. Including Too Much Data

### Wrong

```python
@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    # Including entire customer profile when only ID is needed
    customer_name: String()
    customer_email: String()
    customer_phone: String()
    customer_address: String()
    customer_birth_date: String()
    # ... 20 more customer fields
```

### Correct

```python
@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    customer_id: String(required=True)  # Just the ID
    total_amount: Float(required=True)
    # Only what's necessary to perform the action
```

The handler can look up any other data it needs.

## 5. Making Commands Mutable

### Wrong

```python
# fragment
command = PlaceOrder(order_id="123", customer_id="456", total_amount=99.99)
command.order_id = "789"  # Raises IncorrectUsageError!
```

### Correct

```python
domain.init(traverse=False)

with domain.domain_context():
    # Commands are immutable - create a new instance instead
    command = PlaceOrder(order_id="789", customer_id="456", total_amount=99.99)
```

## 6. Multiple Handlers for One Command

### Wrong

```python
# fragment
@domain.command_handler(part_of="Order")
class OrderHandler:
    @handle(PlaceOrder)
    def handle_place_order(self, command):
        pass

@domain.command_handler(part_of="Inventory")
class InventoryHandler:
    @handle(PlaceOrder)  # Wrong! Same command in two handlers
    def handle_place_order(self, command):
        pass
```

### Correct

```python
@domain.command_handler(part_of="Order")
class OrderHandler:
    @handle(PlaceOrder)  # One handler for this command
    def handle_place_order(self, command):
        # Process order AND raise events for other aggregates
        order = Order(id=command.order_id, customer_id=command.customer_id)
        order.place()
        domain.repository_for(Order).add(order)
        # Events will notify Inventory via event handlers
```

A command has exactly one handler. When several aggregates need to react, raise an event and let their event handlers react to it.

## 7. Confusing Commands with Events

A past-tense command such as `OrderWasPlaced` is an event in disguise, as in section 1. Define the command for the intent and the event for the fact:

```python
# Command: what should happen (imperative)
@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    customer_id: String(required=True)

# Event: what happened (past-tense)
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: String(required=True, identifier=True)
    placed_at: DateTime(required=True)
```

## 8. Forgetting Required Fields

### Wrong

```python
@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier()  # Should be required!
    customer_id: String()  # Should be required!
```

### Correct

```python
@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    customer_id: String(required=True)
```

## 9. Generic Command Names

### Wrong

```python
@domain.command(part_of="Order")
class UpdateOrder:  # Too generic - what update?
    order_id: Identifier(required=True)
    field_name: String()
    new_value: String()
```

### Correct

```python
@domain.command(part_of="Order")
class CancelOrder:  # Specific action
    order_id: Identifier(required=True)
    reason: String(required=True)

@domain.command(part_of="Order")
class ShipOrder:  # Specific action
    order_id: Identifier(required=True)
    tracking_number: String(required=True)
```

## 10. Not Specifying part_of for Concrete Commands

### Wrong

```python
# fragment
@domain.command(abstract=True)
class BaseCommand:
    entity_id: Identifier(required=True)

@domain.command  # Missing part_of! Not abstract, so needs aggregate
class CreateProduct(BaseCommand):
    name: String(required=True)
```

### Correct

```python
@domain.command(abstract=True)
class BaseCommand:
    entity_id: Identifier(required=True)

@domain.command(part_of="Product")  # Concrete commands need part_of
class CreateProduct(BaseCommand):
    name: String(required=True)
```

Only abstract commands can omit `part_of`.

## Related

- [Command Validation](./command-validation.md): Proper field validation
- [Command Processing](./command-processing.md): Correct processing patterns
- [Command Inheritance](./command-inheritance.md): Abstract command patterns
