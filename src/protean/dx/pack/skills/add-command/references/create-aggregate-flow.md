# Create-Aggregate Command Flow

## Overview

Use this pattern when the command introduces a brand-new aggregate into the system (e.g., registering a user, placing an order, creating a project). The handler constructs the aggregate from command data rather than loading it from a repository.

## Walkthrough

### The Aggregate

The command creates a `User`:

```python
@domain.aggregate
class User:
    user_id: Identifier(identifier=True)
    email: String(required=True, max_length=255)
    name: String(required=True, max_length=100)
    status: String(default="pending")

    def register(self):
        self.status = "registered"
```

### The Command

```python
@domain.command(part_of="User")
class RegisterUser:
    user_id: Identifier(required=True)
    email: String(required=True, max_length=255)
    name: String(required=True, max_length=100)
```

The caller provides `user_id` here. It could also be auto-generated.

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

### The Endpoint

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from protean import current_domain


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Wire the commands and handlers once, before the app takes requests
    domain.init()
    try:
        yield
    finally:
        # Release the adapter connections on shutdown, even after an error
        domain.close()


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def domain_context_middleware(request: Request, call_next):
    with domain.domain_context():
        return await call_next(request)


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

## Testing

Test create flows at three levels:
1. **Domain elements**: Verify command, handler, and aggregate registration
2. **Command processing**: Submit command via `domain.process()` and verify aggregate creation
3. **HTTP endpoint**: Use `TestClient` to verify the full HTTP flow

## Related

- [Update-aggregate flow](./update-aggregate-flow.md): For modifying existing aggregates
- [Multiple commands flow](./multiple-commands-flow.md): Adding many commands to one aggregate
