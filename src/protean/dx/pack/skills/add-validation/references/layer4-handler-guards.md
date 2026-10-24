# Layer 4: Handler/Service Guards

Handler guards enforce context-dependent rules that cannot be expressed as field constraints or invariants, because they depend on who is performing the action, external data, or cross-aggregate state.

## Pattern

```python
from datetime import datetime

from protean import handle
from protean.exceptions import ValidationError
from protean.fields import Identifier, String
from protean.utils.globals import current_domain

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

        # Guard 2: Existence check. get() raises ObjectNotFoundError on a miss;
        # get_or_none() returns None so the handler can say why.
        repo = current_domain.repository_for(Account)
        account = repo.get_or_none(command.account_id)
        if account is None:
            raise ValidationError(
                {"account_id": [f"Account {command.account_id} not found"]}
            )

        # Guard 3: Context-dependent check
        if not is_business_hours():
            raise ValidationError({"timing": ["Only during business hours"]})

        # Business logic (Layers 1-3 validate automatically)
        account.close()
        repo.add(account)
```

## Common Guard Patterns

The handler above shows the authorization, existence and timing guards. Each pattern below is a few lines from inside a handler method like `close_account`. They use that method's `command` and `repo`, so they do not run on their own.

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

## Related

- [Layer 3](./layer3-aggregate-invariants.md): Business rules in aggregates
- [Choosing the Right Layer](./choosing-the-right-layer.md): Decision framework
