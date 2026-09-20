# Return Values from Command Handlers

Command handler methods can return values to the caller when commands are processed synchronously.

## Overview

The behavior depends on the processing mode:

| Mode | How to invoke | Return value |
|------|--------------|--------------|
| Synchronous | `domain.process(cmd, asynchronous=False)` | Handler method's return value |
| Asynchronous | `domain.process(cmd)` | Position in event store |

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

# Caller receives the return value
account_id = domain.process(register_cmd, asynchronous=False)
```

## Common Return Patterns

### Return a created identifier

```python
@handle(CreateOrder)
def handle_create(self, command):
    order = Order(order_id=command.order_id, ...)
    domain.repository_for(Order).add(order)
    return order.order_id
```

### Return nothing (void)

```python
@handle(ActivateAccount)
def handle_activate(self, command):
    account = domain.repository_for(Account).get(command.account_id)
    account.activate()
    domain.repository_for(Account).add(account)
    # Implicit return None
```

## Asynchronous Processing

When processing asynchronously (the default), the handler's return value is ignored. `domain.process()` returns the position of the command in the event store:

```python
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

- [Error Handling](./error-handling.md) - What happens when handlers raise exceptions
- `command` - Command processing reference
