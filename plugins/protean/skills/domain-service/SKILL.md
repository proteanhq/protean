---
name: domain-service
description: Define a Protean domain service - a stateless orchestrator that encapsulates complex business logic spanning multiple aggregates. Domain services centralize cross-aggregate operations that don't naturally fit within any single aggregate, while keeping aggregates focused on their core state and behavior. Use when you need to coordinate logic across two or more aggregates, implement a cross-aggregate business rule, orchestrate a domain operation that mutates multiple aggregates in a single transaction, define invariants that span aggregate boundaries, or implement the DDD Domain Service pattern. Domain services are always associated with at least two aggregates via part_of. Supports three flavors: callable class (__call__), class with instance methods, and class with class methods. Supports pre and post invariants for cross-aggregate validation.
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
---

# Domain Service

## Key concepts

Domain services are **stateless orchestrators** for complex business logic that spans multiple aggregates. They exist because some domain operations naturally involve more than one aggregate and shouldn't be forced into either.

- **Stateless**: No internal state between method calls; operate on state provided through parameters
- **Cross-aggregate**: Must be associated with at least two aggregates via `part_of`
- **Pure domain logic**: Focus on domain rules only; no persistence, messaging, or technical concerns
- **Aggregate mutation**: Mutate aggregates to the desired state; persistence is handled by the calling layer (command handlers, application services)

### Typical workflow

1. Application layer loads aggregates via repositories
2. Application layer invokes the domain service, passing aggregates
3. Domain service executes business logic, mutating aggregates
4. Application layer persists the mutated aggregates

## Basic structure

```python
@domain.domain_service(part_of=[Order, Inventory])
class OrderPlacementService:
    def __init__(self, order, inventories):
        super().__init__(*(order, inventories))
        self.order = order
        self.inventories = inventories

    def place_order(self):
        for item in self.order.items:
            inventory = next(
                (i for i in self.inventories if i.product_id == item.product_id), None
            )
            inventory.reserve_stock(item.quantity)
        self.order.confirm()
```

## Three flavors

### 1. Callable class (`__call__`)

Best for a single business operation. Instantiate and call:

```python
@domain.domain_service(part_of=[Order, Inventory])
class place_order:
    def __init__(self, order, inventories):
        super().__init__(*(order, inventories))
        self.order = order
        self.inventories = inventories

    def __call__(self):
        # Business logic here
        ...

# Usage:
place_order(order, [inventory])()
```

### 2. Class with instance methods

Best for multiple related operations on the same aggregates:

```python
@domain.domain_service(part_of=[Order, Inventory])
class OrderPlacementService:
    def __init__(self, order, inventories):
        super().__init__(*(order, inventories))
        self.order = order
        self.inventories = inventories

    def place_order(self):
        ...

# Usage:
service = OrderPlacementService(order, [inventory])
service.place_order()
```

### 3. Class with class methods

Best when no invariants are needed; stateless functional style:

```python
@domain.domain_service(part_of=[Order, Inventory])
class OrderPlacementService:
    @classmethod
    def place_order(cls, order, inventories):
        # Business logic here
        ...
        return order, inventories

# Usage:
order, inventories = OrderPlacementService.place_order(order, [inventory])
```

## Key rules

1. **Must associate with 2+ aggregates**: `part_of=[Agg1, Agg2]` is required. A domain service with fewer than two aggregates raises `IncorrectUsageError`.
2. **Use `@domain.domain_service` decorator**: Or register with `domain.register(MyService, part_of=[Agg1, Agg2])`.
3. **Call `super().__init__()`**: When using instance methods or callable class, always call `super().__init__(*(aggregates))` in `__init__`.
4. **Stateless between calls**: Domain services hold no state between invocations. State comes from aggregates passed in.
5. **Don't persist**: Domain services mutate aggregates but never call repositories. The calling layer handles persistence.
6. **Invariants span aggregates**: Use `@invariant.pre` and `@invariant.post` for validations that involve multiple aggregates.
7. **Private methods use underscore prefix**: Prefix helper methods with `_` to avoid them being wrapped with invariant checks. Missing underscore causes `RecursionError`.
8. **Choose flavor based on needs**: Callable class for single operation, instance methods for multiple operations, class methods when no invariants needed.
9. **Don't propagate state changes in more than one aggregate**: Even though domain services can access multiple aggregates, use events and eventual consistency for cross-aggregate state synchronization. The command handler should only persist the primary aggregate.
10. **Review regularly**: As the domain model matures, revisit whether logic in a domain service should be moved to an aggregate or vice versa.

## Domain service options

| Option | Purpose | Required | Default |
|--------|---------|----------|---------|
| `part_of` | List of 2+ aggregates this service orchestrates | Yes | None |

## Invariants

Domain services support `@invariant.pre` and `@invariant.post` decorators for cross-aggregate validation:

```python
@domain.domain_service(part_of=[Order, Inventory])
class OrderPlacementService:
    def __init__(self, order, inventories):
        super().__init__(*(order, inventories))
        self.order = order
        self.inventories = inventories

    @invariant.pre
    def inventory_should_have_sufficient_stock(self):
        for item in self.order.items:
            inventory = next(
                (i for i in self.inventories if i.product_id == item.product_id), None
            )
            if inventory is None or inventory.quantity < item.quantity:
                raise ValidationError({"_service": ["Product is out of stock"]})

    @invariant.post
    def totals_should_match(self):
        # Validate post-conditions after mutation
        ...

    def __call__(self):
        # Business logic
        ...
```

- **Pre invariants**: Run before the service method executes; validate preconditions
- **Post invariants**: Run after the service method executes; validate postconditions
- Multiple invariant violations are collected and raised together as a single `ValidationError`
- If a pre invariant fails, the service method is **not executed**

## Common mistakes

### Associating with only one aggregate

```python
# Wrong - raises IncorrectUsageError
@domain.domain_service(part_of=[Order])
class OrderService:
    ...
```

```python
# Correct - needs 2+ aggregates
@domain.domain_service(part_of=[Order, Inventory])
class OrderPlacementService:
    ...
```

If your logic only involves one aggregate, it belongs **in the aggregate itself**.

### Forgetting super().__init__()

```python
# Wrong - won't track aggregates properly
class OrderPlacementService:
    def __init__(self, order, inventories):
        self.order = order
        self.inventories = inventories
```

```python
# Correct
class OrderPlacementService:
    def __init__(self, order, inventories):
        super().__init__(*(order, inventories))
        self.order = order
        self.inventories = inventories
```

### Persisting inside the domain service

```python
# Wrong - domain services don't handle persistence
def place_order(self):
    self.order.confirm()
    domain.repository_for(Order).add(self.order)  # Don't do this!
```

```python
# Correct - return mutated aggregates, let caller persist
def place_order(self):
    self.order.confirm()
    # Calling command handler will persist
```

### Missing underscore on private methods

```python
# Wrong - causes RecursionError due to invariant wrapping
def calculate_total(self):
    ...
```

```python
# Correct - underscore prefix prevents invariant wrapping
def _calculate_total(self):
    ...
```

## Detailed references

### Core concepts
- [Callable class pattern](references/callable-class.md) - Single-operation domain service
- [Instance methods pattern](references/instance-methods.md) - Multi-operation domain service
- [Class methods pattern](references/class-methods.md) - Stateless functional domain service
- [Invariants](references/invariants.md) - Pre/post validation across aggregates

### Complete examples
- [Callable class example](assets/domain_service_callable.py) - Order placement as callable
- [Instance methods example](assets/domain_service_instance_methods.py) - Order placement with named methods
- [Class methods example](assets/domain_service_class_methods.py) - Order placement with class methods
- [With invariants example](assets/domain_service_with_invariants.py) - Full pre/post invariant validation

### Related skills
- `aggregate` - Domain aggregates that domain services orchestrate
- `command-handler` - Where domain services are typically invoked from
- `event` - Events raised by aggregates during domain service operations
- `value-object` - Value objects used within aggregates passed to domain services

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
