# Command Anti-Patterns

Common mistakes when working with commands and how to avoid them.

## Overview

Commands are deceptively simple but have specific constraints that, when violated, lead to fragile designs. This guide covers the most common anti-patterns and their correct alternatives.

## 1. Using Past-Tense Verbs Instead of Imperative

### Wrong

```python
@domain.command(part_of="Order")
class OrderPlaced:  # Past-tense - this is an EVENT, not a command!
    order_id: Identifier(required=True)
```

```python
@domain.command(part_of="Payment")
class PaymentProcessed:  # Wrong - sounds like something that happened
    payment_id: Identifier(required=True)
```

### Correct

```python
@domain.command(part_of="Order")
class PlaceOrder:  # Imperative - describes the intent to act
    order_id: Identifier(required=True)
```

```python
@domain.command(part_of="Payment")
class ProcessPayment:  # Imperative - tells the system what to do
    payment_id: Identifier(required=True)
```

**Why it matters:** Commands represent intent to act. Past-tense names suggest events (facts that already occurred). Using the right naming convention makes the domain model clear and self-documenting.

## 2. Not Associating Commands with Aggregates

### Wrong

```python
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

**Why it matters:** Commands must be associated with aggregates. Aggregates are the entry point for all modifications, and this association is required by Protean (raises `IncorrectUsageError` without it).

## 3. Including Entities in Commands

### Wrong

```python
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

**Why it matters:** Commands are DTOs (Data Transfer Objects). They can only contain simple fields and value objects, not entities or aggregates. Entities have identity and lifecycle; commands carry intent.

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

**Why it matters:** Commands should carry only the data necessary for the intended action. The handler can look up additional data if needed.

## 5. Making Commands Mutable

### Wrong

```python
command = PlaceOrder(order_id="123", customer_id="456")
command.order_id = "789"  # Raises IncorrectUsageError!
```

### Correct

```python
# Commands are immutable - create a new instance instead
command = PlaceOrder(order_id="789", customer_id="456")
```

**Why it matters:** Commands are immutable. This guarantees the intent captured at creation time cannot be tampered with during processing.

## 6. Multiple Handlers for One Command

### Wrong

```python
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
        order = Order(...)
        order.place()
        self.repository.add(order)
        # Events will notify Inventory via event handlers
```

**Why it matters:** A command can only be handled by ONE command handler. If you need multiple aggregates to react, use events for cross-aggregate communication.

## 7. Confusing Commands with Events

### Wrong

```python
# Using a command where an event should be used
@domain.command(part_of="Order")
class OrderWasPlaced:  # This is an event concept!
    order_id: Identifier(required=True)
    placed_at: DateTime(required=True)
```

### Correct

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

**Why it matters:** Commands and events are complementary but distinct. Commands represent intent (what should happen), events represent facts (what happened). Mixing them blurs domain boundaries.

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

**Why it matters:** Commands carry intent for a specific action. Critical fields should always be marked as required to ensure commands are complete and actionable.

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

**Why it matters:** Command names should clearly communicate the intent. Specific names make the domain model explicit and commands self-documenting.

## 10. Not Specifying part_of for Concrete Commands

### Wrong

```python
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

**Why it matters:** Only abstract commands can omit `part_of`. Concrete commands must always be associated with an aggregate.

## Summary Checklist

When creating commands, ensure:

- [ ] Command name uses imperative verbs (PlaceOrder, not OrderPlaced)
- [ ] Command specifies `part_of` parameter (unless abstract)
- [ ] Command only contains simple fields and value objects (no entities)
- [ ] Command includes only data necessary for the action
- [ ] Command fields that are essential are marked `required=True`
- [ ] Command name is specific and descriptive (not generic "Update" or "Process")
- [ ] Only one handler processes each command
- [ ] Commands and events are not confused (commands = intent, events = facts)

## Related

- [Command Validation](./command-validation.md) - Proper field validation
- [Command Processing](./command-processing.md) - Correct processing patterns
- [Command Inheritance](./command-inheritance.md) - Abstract command patterns
