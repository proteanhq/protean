# Request Validation

How incoming request bodies are checked before and after they become domain
commands.

## Overview

A request is checked in two places, and each gives its own status code:

1. **Pydantic, at the HTTP boundary.** Is the body well formed? Are the
   required keys there, with the right types? FastAPI checks this before the
   endpoint runs and returns **422** when it fails.
2. **Protean, in the domain.** Do the values satisfy the command's field
   rules (length, range, required) and the aggregate's rules? A failed field
   rule raises `ValidationError`, which `register_exception_handlers` turns
   into **400**.

## Code

The complete implementation is in
[assets/api_endpoint_with_pydantic.py](../assets/api_endpoint_with_pydantic.py).

## Walkthrough

### The command carries the domain rules

```python
from protean.utils.globals import current_domain


@domain.aggregate
class Account:
    account_id = Identifier(identifier=True)
    email = String(required=True)
    name = String(required=True, max_length=50)


@domain.command(part_of=Account)
class RegisterAccount:
    account_id = Identifier(required=True)
    email = String(required=True)
    name = String(required=True, max_length=50)


@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(RegisterAccount)
    def register(self, command: RegisterAccount) -> str:
        account = Account(
            account_id=command.account_id,
            email=command.email,
            name=command.name,
        )
        current_domain.repository_for(Account).add(account)
        return account.account_id
```

### The Pydantic model checks the shape

```python
from pydantic import BaseModel, Field


class RegisterAccountRequest(BaseModel):
    account_id: str = Field(..., min_length=1)
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str = Field(..., min_length=1)
```

- `pattern` checks the email format at the HTTP boundary.
- `min_length=1` rejects empty strings.
- The name's 50-character limit is a domain rule. It lives on the command.
- FastAPI builds the OpenAPI schema from this model, so it documents the API
  for clients.

### From the Pydantic model to the command

```python
from fastapi import APIRouter

router = APIRouter(prefix="/accounts")


@router.post("/register", status_code=201)
def register_account(body: RegisterAccountRequest):
    command = RegisterAccount(
        account_id=body.account_id,
        email=body.email,
        name=body.name,
    )
    account_id = current_domain.process(command, asynchronous=False)
    return {"account_id": account_id, "status": "registered"}
```

The endpoint maps each field of the validated `body` to the command by hand.
This keeps the translation visible, and the Pydantic model and the command can
change separately.

### FastAPI's 422

When the body does not match the model, FastAPI returns 422 before the
endpoint runs:

```json
{
  "detail": [
    {
      "type": "string_pattern_mismatch",
      "loc": ["body", "email"],
      "msg": "String should match pattern '^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$'",
      "input": "not-an-email",
      "ctx": {"pattern": "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$"}
    }
  ]
}
```

### Protean's 400

A name of 60 characters passes the model and fails the command's
`max_length=50`. The `RegisterAccount` constructor raises `ValidationError`,
and the client gets 400 with the messages for each failing field:

```json
{
  "error": {"name": ["String should have at most 50 characters"]},
  "correlation_id": "94068d166ee746f892cf5aa38746dc9a"
}
```

Neither case needs error handling code in the endpoint. Let `ValidationError`
propagate to the registered handler.

## When to use Pydantic vs a raw dict

| Approach | Use when |
|----------|----------|
| Pydantic model | Public APIs, format checks such as email, a documented schema |
| `payload: dict` | Internal APIs and small payloads, where the command's fields do all the checking |

With `payload: dict`, every bad value reaches the command and gives a 400.
Pydantic models are recommended for public-facing APIs.

## Related

- [Response Patterns](./response-patterns.md) - The full exception-to-status map
- [Anti-patterns](./anti-patterns.md) - Common validation mistakes
- [command skill](../../command/SKILL.md) - Domain command definitions
