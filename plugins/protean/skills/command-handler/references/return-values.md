# Return Values from Command Handlers

## Overview

| Mode | How to invoke | Return value |
|------|--------------|--------------|
| Synchronous | `domain.process(cmd, asynchronous=False)` | Handler method's return value |
| Asynchronous | `domain.process(cmd)` | Position in event store |

The examples on this page use these elements:

```python
from protean import handle
from protean.fields import Identifier, String

@domain.aggregate
class Account:
    account_id: Identifier(identifier=True)
    email: String(required=True)
    status: String(default="pending")

    def activate(self):
        self.status = "active"

@domain.command(part_of="Account")
class RegisterAccount:
    account_id: Identifier(required=True)
    email: String(required=True)

@domain.command(part_of="Account")
class ActivateAccount:
    account_id: Identifier(required=True)
```

## Synchronous Return Values

When processing synchronously, the handler's return value passes through to the caller:

```python
@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(RegisterAccount)
    def handle_register(self, command: RegisterAccount):
        account = Account(
            account_id=command.account_id,
            email=command.email,
        )
        domain.repository_for(Account).add(account)
        return account.account_id  # Returned to caller

    @handle(ActivateAccount)
    def handle_activate(self, command: ActivateAccount):
        account = domain.repository_for(Account).get(command.account_id)
        account.activate()
        domain.repository_for(Account).add(account)
        # Implicit return None

domain.init(traverse=False)

with domain.domain_context():
    register_cmd = RegisterAccount(account_id="ACC-001", email="jane@example.com")
    # Caller receives the return value
    account_id = domain.process(register_cmd, asynchronous=False)
    assert account_id == "ACC-001"
```

## Common Return Patterns

### Return nothing (void)

`handle_activate` in the handler above returns nothing, so the caller gets `None`:

```python
with domain.domain_context():
    result = domain.process(
        ActivateAccount(account_id="ACC-001"), asynchronous=False
    )
    assert result is None
```

## Asynchronous Processing

When processing asynchronously (the default), the handler's return value is ignored. `domain.process()` returns the position of the command in the event store:

```python
with domain.domain_context():
    cmd = RegisterAccount(account_id="ACC-002", email="sam@example.com")
    position = domain.process(cmd)  # Returns event store position
```

## Configuring Default Processing Mode

Set the domain-wide default in configuration:

```toml
# domain.toml
command_processing = "sync"  # or "async" (default)
```

Or in code:

```python
domain.config["command_processing"] = "sync"
```

## Related

- [Error Handling](./error-handling.md): What happens when handlers raise exceptions
- `command`: Command processing reference
