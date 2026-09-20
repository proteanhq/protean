# Anti-Patterns in Value Object Extraction

## Over-extraction

Extracting VOs where none are needed:

```python
# Bad: VO for a single field with no behavior
@domain.value_object
class CustomerName:
    value = String(required=True)
# Just use: name = String(required=True) on the aggregate

# Good: VO when there IS behavior or multiple fields
@domain.value_object
class PersonName:
    first = String(required=True)
    last = String(required=True)

    def full(self) -> str:
        return f"{self.first} {self.last}"
```

## Anemic value objects

VOs with only fields and no behavior — these are just struct wrappers:

```python
# Questionable: no behavior
@domain.value_object
class Money:
    amount = Float(required=True)
    currency = String(default="USD")
    # No methods — is this better than two fields?

# Better: with behavior
@domain.value_object
class Money:
    amount = Float(required=True)
    currency = String(default="USD")

    def add(self, other): ...
    def multiply(self, factor): ...
    def is_zero(self): ...
```

## Breaking event contracts

Changing event field structure without versioning:

```python
# Dangerous: existing consumers expect flat fields
@domain.event(part_of="Order")
class OrderPlaced:
    # Was: total_amount = Float(), total_currency = String()
    total = ValueObject(Money)  # Breaks all existing consumers!

# Safe: version bump + upcaster
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 2
    total = ValueObject(Money)
```

## Inconsistent extraction

Extracting in one place but not another:

```python
# Inconsistent: Money on aggregate but not on entity
@domain.aggregate
class Order:
    total = ValueObject(Money)  # Extracted

@domain.entity(part_of="Order")
class LineItem:
    unit_price_amount = Float()  # Still primitive!
    unit_price_currency = String()
```

Always extract consistently across all usages.

## Related

- [migration-guide.md](migration-guide.md) — Safe migration steps
- [common-value-objects.md](common-value-objects.md) — Reference implementations
