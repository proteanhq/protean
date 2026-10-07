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
        self.order = order
        self.inventory = inventory
```

## Stateless — Never Persist

Domain services are stateless. They receive aggregates, perform cross-aggregate logic,
and return. The **calling handler** persists one aggregate, the primary one. The
other aggregates change through events: an event handler in the cluster that owns
the event issues a command to the other aggregate.

## `super().__init__()` Stores the Aggregates

`BaseDomainService.__init__` saves the aggregates it receives on
`self._aggregates` and does nothing else. Call `super().__init__(order, inventory)`
when your code reads `self._aggregates`. Protean wires invariants when it
registers the service, so leaving the call out does not turn them off.

## Prefix Helper Methods with `_`

Protean wraps every public method and `__call__` with the invariant checks. A
public helper called from another public method runs the invariants again. An
invariant that calls a public helper never ends: the helper's wrapper runs the
invariant again. Start helper names with `_` so they are not wrapped:

```python
@domain.domain_service(part_of=[Order, Inventory])
class PricingService:
    def calculate_final_price(self):
        base = self._get_base_price()
        discount = self._apply_bulk_discount()
        return base - discount

    def _get_base_price(self):
        # Helper: the underscore prefix keeps it unwrapped
        ...
```
