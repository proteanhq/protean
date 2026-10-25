# Anti-Patterns in Value Object Extraction

## Over-extraction

Extracting VOs where none are needed:

```python
# fragment
# Bad: VO for a single field with no behavior
@domain.value_object
class CustomerName:
    value = String(required=True)
# Just use: name = String(required=True) on the aggregate
```

```python
# Good: VO when there IS behavior or multiple fields
@domain.value_object
class PersonName:
    first = String(required=True)
    last = String(required=True)

    def full(self) -> str:
        return f"{self.first} {self.last}"
```

## Inconsistent extraction

Extracting in one place but not another:

```python
# fragment
# Inconsistent: Money on aggregate but not on entity
@domain.aggregate
class Order:
    total = ValueObject(Money)  # Extracted

@domain.entity(part_of="Order")
class LineItem:
    unit_price_amount = Decimal(precision=19, scale=4)  # Still primitive!
    unit_price_currency = String()
```

Extract the concept on every aggregate and entity that carries it.

## Related

- [migration-guide.md](migration-guide.md): Safe migration steps
- [common-value-objects.md](common-value-objects.md): Reference implementations
