# Commands with Value Objects

A command can carry a value object, such as `Money` or `Address`, through a `ValueObject()` field. The same value object class can be used in commands, events and aggregates.

## Code

The complete implementation is in [assets/command_with_value_object.py](../assets/command_with_value_object.py).

## Common Value Objects in Commands

The commands on this page belong to these aggregates:

```python
@domain.aggregate
class Order:
    customer_id: String(required=True)

@domain.aggregate
class Customer:
    name: String(required=True)

@domain.aggregate
class User:
    email: String(required=True)
```

### Money

```python
@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    customer_id: String(required=True)
    total = ValueObject(Money, required=True)
```

### Address

```python
@domain.value_object
class Address:
    street: String(required=True, max_length=200)
    city: String(required=True, max_length=100)
    state: String(max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(required=True, max_length=50)

@domain.command(part_of="Customer")
class UpdateCustomerAddress:
    customer_id: Identifier(required=True)
    new_address = ValueObject(Address, required=True)
```

## Multiple Value Objects in One Command

```python
@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    customer_id: String(required=True)

    # Multiple value objects
    total = ValueObject(Money, required=True)
    shipping_address = ValueObject(Address, required=True)
    billing_address = ValueObject(Address)  # Optional
```

## Value Objects vs Simple Fields

Use a value object when several attributes form one concept (`Money` has an amount and a currency), when the data needs its own validation, or when the concept is reused. Use a simple field for a single value used by one command:

```python
@domain.command(part_of="User")
class ChangeUserEmail:
    user_id: Identifier(required=True)
    new_email: String(required=True)  # Just a string
```

## Related

- [Command Validation](./command-validation.md): Validation on command fields
- [Anti-patterns](./anti-patterns.md): Common mistakes
- `value-object`: Detailed value object patterns
