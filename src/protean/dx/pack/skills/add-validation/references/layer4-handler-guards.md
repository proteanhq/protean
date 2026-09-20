# Layer 4: Handler/Service Guards

Handler guards enforce context-dependent rules that cannot be expressed as field constraints or invariants — because they depend on who is performing the action, external data, or cross-aggregate state.

## Code

The complete implementation is in [assets/validation_layer4_handler_guards.py](../assets/validation_layer4_handler_guards.py).

## Pattern

```python
@domain.command_handler(part_of=SomeAggregate)
class SomeCommandHandler:

    @handle(SomeCommand)
    def handle_command(self, command: SomeCommand):
        # Guard 1: Authorization
        if command.requested_by_role not in ALLOWED_ROLES:
            raise ValidationError({"authorization": ["Not authorized"]})

        # Guard 2: Existence check
        entity = domain.repository_for(SomeAggregate).get(command.entity_id)

        # Guard 3: Context-dependent check
        if not is_business_hours():
            raise ValidationError({"timing": ["Only during business hours"]})

        # Business logic (Layers 1-3 validate automatically)
        entity.do_something()
        domain.repository_for(SomeAggregate).add(entity)
```

## Common Guard Patterns

### Authorization (role-based)
```python
ALLOWED_ROLES = {"admin", "manager"}

if command.role not in ALLOWED_ROLES:
    raise ValidationError({"authorization": ["Insufficient permissions"]})
```

### Existence check
```python
entity = repo.get(command.entity_id)
# ObjectNotFoundError raised automatically if not found
```

### Cross-aggregate consistency
```python
customer = domain.repository_for(Customer).get(command.customer_id)
if customer.status != "active":
    raise ValidationError({"customer": ["Customer account is inactive"]})
```

### Rate limiting / quota
```python
count = repo.count_by_user(command.user_id)
if count >= MAX_ITEMS:
    raise ValidationError({"quota": [f"Maximum {MAX_ITEMS} items reached"]})
```

## When to Use Layer 4

- **Authorization**: Who can perform this action?
- **Existence**: Does the referenced entity exist?
- **Cross-aggregate**: What is the state of another aggregate?
- **Temporal**: Is this the right time for this action?
- **Quota/rate**: Has a limit been reached?

## When NOT to Use Layer 4

- Business rules intrinsic to the aggregate → Layer 3
- Single-field format rules → Layer 1
- Domain concept rules → Layer 2

## Key Principle

**Handlers are for orchestration and guards, not business rules.** Business rules belong in aggregates (Layer 3) where they are enforced regardless of how the aggregate is accessed.

## Related

- [Layer 3](./layer3-aggregate-invariants.md) - Business rules in aggregates
- [Choosing the Right Layer](./choosing-the-right-layer.md) - Decision framework
