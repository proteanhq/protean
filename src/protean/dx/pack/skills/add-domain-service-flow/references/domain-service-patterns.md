# Domain Service Patterns

## Callable pattern (recommended)

The most common pattern. Instantiate with aggregates, call to execute.

```python
@domain.domain_service(part_of=[Order, Inventory])
class PlaceOrderService:
    def __init__(self, order, inventories):
        BaseDomainService.__init__(self, *(order, inventories))
        self.order = order
        self.inventories = inventories

    def __call__(self):
        # Business logic here
        ...
```

Usage:
```python
PlaceOrderService(order, inventories)()
```

## Important: BaseDomainService.__init__

Always call `BaseDomainService.__init__(self, *(aggregates))` in `__init__`. This is required for invariant support.

`super().__init__(*(aggregates))` works too: the framework rebinds each method's `__class__` cell after it rebuilds the class, so zero-argument `super()` resolves correctly. These examples call `BaseDomainService.__init__` explicitly for clarity.

## Pre and post invariants

Domain services support the same `@invariant.pre` and `@invariant.post` decorators as aggregates.

- **Pre invariants**: Run before `__call__` — validate preconditions
- **Post invariants**: Run after `__call__` — validate postconditions

```python
@invariant.pre
def sufficient_balance(self):
    if self.source.balance < self.amount:
        raise ValidationError({"_service": ["Insufficient balance"]})

@invariant.post
def transfer_recorded(self):
    if self.source.balance + self.target.balance != self.original_total:
        raise ValidationError({"_service": ["Balance mismatch"]})
```

## Wiring into command handlers

The command handler is responsible for:
1. Loading aggregates from repositories
2. Instantiating and calling the domain service
3. Persisting all affected aggregates

```python
@handle(TransferFundsCommand)
def handle_transfer(self, command):
    source = domain.repository_for(Account).get(command.source_id)
    target = domain.repository_for(Account).get(command.target_id)

    TransferFunds(source, target, command.amount)()

    domain.repository_for(Account).add(source)
    domain.repository_for(Account).add(target)
```
