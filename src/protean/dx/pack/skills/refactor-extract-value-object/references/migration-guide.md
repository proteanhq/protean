# Migration Guide

How to safely migrate from primitive fields to value objects in a running system.

## Step-by-step

### 1. Add the value object class

Create the VO in a shared location if used across aggregates, or alongside the aggregate if used only once.

### 2. Add the new VO field alongside old fields

Don't remove the old fields yet — add the new field in parallel:

```python
@domain.aggregate
class Order:
    # Old fields (keep temporarily)
    total_amount = Float(default=0.0)
    total_currency = String(default="USD")
    # New field
    total = ValueObject(Money)
```

### 3. Update write paths

Change all methods that set the primitive fields to also set the VO field:

```python
def place(self, items):
    calculated = sum(i.price * i.qty for i in items)
    self.total_amount = calculated  # Old (keep)
    self.total = Money(amount=calculated)  # New
```

### 4. Update read paths

Change all code that reads primitive fields to read from the VO:

```python
# Before
if order.total_amount > MAX_ORDER:
    ...

# After
if order.total.amount > MAX_ORDER:
    ...
```

### 5. Verify with tests

Run the full test suite. Both old and new fields should have consistent values.

### 6. Remove old fields

Once all read/write paths use the VO, remove the primitive fields:

```python
@domain.aggregate
class Order:
    total = ValueObject(Money)  # Only the VO remains
```

### 7. Handle event schema changes

If events carry the old field names, you need an upcaster:

```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 2
    order_id = Identifier(required=True)
    total = ValueObject(Money)  # Was: total_amount + total_currency

@domain.upcaster(event_cls=OrderPlaced, version=1)
class OrderPlacedV1Upcaster:
    def upcast(self, data: dict) -> dict:
        data["total"] = {
            "amount": data.pop("total_amount", 0.0),
            "currency": data.pop("total_currency", "USD"),
        }
        return data
```

## When NOT to extract

- **Independent timestamps**: `created_at` + `updated_at` are not a DateRange
- **Unrelated fields that happen to be the same type**: Two `String` fields don't automatically form a VO
- **Fields used only for storage/display**: If there's no behavior to encapsulate, a VO adds complexity without value
- **When it breaks your API contract**: If external consumers depend on flat field names, consider the migration cost

## Related

- [common-value-objects.md](common-value-objects.md) — Catalog of common VOs
- [upcaster SKILL.md](../../upcaster/SKILL.md) — Event schema migration
