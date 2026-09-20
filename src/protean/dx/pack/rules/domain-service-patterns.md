---
description: Domain service patterns — multi-aggregate coordination, statelessness, and initialization rules
globs: "**/*.py"
---

# Domain Service Patterns

## Must Span 2+ Aggregates

Domain services encapsulate business logic that spans multiple aggregates. Logic involving
a single aggregate belongs in the aggregate itself:

```python
@domain.domain_service(part_of=[Order, Inventory])
class OrderFulfillmentService:
    def __init__(self, order, inventory):
        super().__init__(order, inventory)
        # ...
```

## Stateless — Never Persist

Domain services are stateless. They receive aggregates, perform cross-aggregate logic,
and return. The **calling handler** is responsible for persisting the aggregates.

## `super().__init__()` Required

Always call `super().__init__(*(aggregates))` when using instance methods.

## Prefix Helper Methods with `_`

Helper methods must start with `_` to avoid being wrapped by Protean's invariant
checking mechanism, which would cause `RecursionError`:

```python
@domain.domain_service(part_of=[Order, Inventory])
class PricingService:
    def calculate_final_price(self):
        base = self._get_base_price()
        discount = self._apply_bulk_discount()
        return base - discount

    def _get_base_price(self):
        # Helper — underscore prefix is required
        ...
```
