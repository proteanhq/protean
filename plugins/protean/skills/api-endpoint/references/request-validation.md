# Request Validation

How to validate incoming HTTP request payloads using Pydantic models before constructing domain commands.

## Overview

API endpoints need two layers of validation:

1. **HTTP/format validation** (Pydantic) - Is the request well-formed? Are required fields present? Are types correct?
2. **Domain validation** (Protean commands/aggregates) - Does the data satisfy business rules?

Pydantic handles layer 1 at the API boundary. Protean handles layer 2 inside the domain.

## Code

The complete implementation is in [assets/api_endpoint_with_pydantic.py](../assets/api_endpoint_with_pydantic.py).

Key highlights:
- Pydantic `BaseModel` subclass defines the expected request shape
- FastAPI automatically validates and returns 422 for invalid input
- Validated data is mapped to Protean command fields
- Domain commands carry the validated intent into the domain

## Walkthrough

### Pydantic Request Model

```python
from pydantic import BaseModel, Field

class RegisterAccountRequest(BaseModel):
    account_id: str = Field(..., min_length=1)
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str = Field(..., min_length=1, max_length=100)
```

Key design decisions:
- `pattern` constraint validates email format at the HTTP boundary using a regex
- `Field(..., min_length=1)` ensures non-empty strings
- The model documents the API contract for clients (FastAPI generates OpenAPI schema from it)

### From Pydantic Model to Command

```python
@app.post("/accounts/register", status_code=201)
async def register_account(body: RegisterAccountRequest):
    command = RegisterAccount(
        account_id=body.account_id,
        email=body.email,
        name=body.name,
    )
    result = current_domain.process(command, asynchronous=False)
```

The endpoint receives the validated `body` and maps fields one-to-one to the domain command. This mapping is intentionally explicit -- it makes the translation visible and keeps the Pydantic model decoupled from the command.

### Automatic 422 Responses

FastAPI returns a 422 Unprocessable Entity when validation fails:

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "email"],
      "msg": "value is not a valid email address",
      "input": "not-an-email"
    }
  ]
}
```

No custom error handling code is needed for input validation -- FastAPI handles it.

## When to Use Pydantic vs Raw JSON

| Approach | Use When |
|----------|----------|
| Pydantic model | Complex payloads, email/URL validation, documented API |
| Raw `request.json()` | Simple payloads, internal APIs, rapid prototyping |

Both are valid. Pydantic models are recommended for public-facing APIs.

## Related

- [Response Patterns](./response-patterns.md) - Structuring HTTP responses
- [Anti-patterns](./anti-patterns.md) - Common validation mistakes
- [command skill](../../command/SKILL.md) - Domain command definitions
