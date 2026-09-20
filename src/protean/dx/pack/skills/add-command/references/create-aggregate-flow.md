# Create-Aggregate Command Flow

This reference explains the complete flow for adding a command that creates a new aggregate instance.

## Overview

Use this pattern when the command introduces a brand-new aggregate into the system (e.g., registering a user, placing an order, creating a project). The handler constructs the aggregate from command data rather than loading it from a repository.

## Code

The complete implementation is in [assets/add_command_create_flow.py](../assets/add_command_create_flow.py).

Key highlights:
- Command named with imperative verb: `RegisterUser`
- Handler constructs a new `User` aggregate from command fields
- Handler calls an aggregate method (`register()`) to apply business logic
- Handler persists via `domain.repository_for(User).add(user)`
- POST endpoint maps JSON payload to command fields

## Walkthrough

### The Command

```python
@domain.command(part_of="User")
class RegisterUser:
    user_id: Identifier(required=True)
    email: String(required=True, max_length=255)
    name: String(required=True, max_length=100)
```

- `part_of="User"` (string) associates the command with the User aggregate
- Fields mirror what the handler needs to construct the aggregate
- The `user_id` is provided by the caller (could also be auto-generated)

### The Handler (Create Pattern)

```python
@domain.command_handler(part_of=User)
class UserCommandHandler:
    @handle(RegisterUser)
    def handle_register_user(self, command: RegisterUser):
        user = User(
            user_id=command.user_id,
            email=command.email,
            name=command.name,
        )
        user.register()
        domain.repository_for(User).add(user)
        return user.user_id
```

The create pattern has four steps:
1. **Construct** the aggregate from command data
2. **Call** the aggregate method that applies business logic
3. **Persist** using `domain.repository_for(Aggregate).add()`
4. **Return** an identifier for the caller

Note: `part_of=User` uses the class reference (not a string).

### The Endpoint

```python
@app.post("/users/register", status_code=201)
async def register_user(request: Request):
    payload = await request.json()
    command = RegisterUser(
        user_id=payload["user_id"],
        email=payload["email"],
        name=payload["name"],
    )
    result = current_domain.process(command, asynchronous=False)
    return JSONResponse(status_code=201, content={"user_id": result, "status": "registered"})
```

- HTTP POST for creation (returns 201)
- Constructs command from JSON payload
- Uses `current_domain.process()` for synchronous processing
- Returns the handler's return value in the response

## HTTP Verb Choice

| Operation | HTTP Method | Status Code | Example Route |
|-----------|-------------|-------------|---------------|
| Create resource | POST | 201 Created | `POST /users/register` |
| Create with action | POST | 201 Created | `POST /orders` |

## Testing

Test create flows at three levels:
1. **Domain elements** - Verify command, handler, and aggregate registration
2. **Command processing** - Submit command via `domain.process()` and verify aggregate creation
3. **HTTP endpoint** - Use `TestClient` to verify the full HTTP flow

## Related

- [Update-aggregate flow](./update-aggregate-flow.md) - For modifying existing aggregates
- [Multiple commands flow](./multiple-commands-flow.md) - Adding many commands to one aggregate
