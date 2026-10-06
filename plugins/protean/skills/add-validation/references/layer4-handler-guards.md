# Layer 4: Handler/Service Guards

Handler guards enforce context-dependent rules that cannot be expressed as field constraints or invariants — because they depend on who is performing the action, external data, or cross-aggregate state.

## Code

The complete implementation is in [assets/validation_layer4_handler_guards.py](../assets/validation_layer4_handler_guards.py).

## Pattern

```python
from datetime import datetime

from protean.exceptions import ValidationError

ALLOWED_ROLES = {"admin", "manager"}


def is_business_hours() -> bool:
    return 9 <= datetime.now().hour < 17


@domain.aggregate
class Account:
    status: String(default="open")

    def close(self):
        self.status = "closed"


@domain.command(part_of=Account)
class CloseAccount:
    account_id: Identifier(required=True)
    requested_by_role: String(required=True)


@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(CloseAccount)
    def close_account(self, command: CloseAccount):
        # Guard 1: Authorization
        if command.requested_by_role not in ALLOWED_ROLES:
            raise ValidationError({"authorization": ["Not authorized"]})

        # Guard 2: Existence check. get() raises ObjectNotFoundError on a miss.
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)

        # Guard 3: Context-dependent check
        if not is_business_hours():
            raise ValidationError({"timing": ["Only during business hours"]})

        # Business logic (Layers 1-3 validate automatically)
        account.close()
        repo.add(account)
```

## Common Guard Patterns

### Authorization (role-based)
```python
# fragment
ALLOWED_ROLES = {"admin", "manager"}

if command.role not in ALLOWED_ROLES:
    raise ValidationError({"authorization": ["Insufficient permissions"]})
```

### Existence check
```python
# fragment
entity = repo.get(command.entity_id)
# ObjectNotFoundError raised automatically if not found

# To report a missing entity as a validation error instead:
entity = repo.get_or_none(command.entity_id)
if entity is None:
    raise ValidationError({"entity_id": ["Not found"]})
```

### Cross-aggregate consistency
```python
# fragment
customer = current_domain.repository_for(Customer).get(command.customer_id)
if customer.status != "active":
    raise ValidationError({"customer": ["Customer account is inactive"]})
```

### Rate limiting / quota
```python
# fragment
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
