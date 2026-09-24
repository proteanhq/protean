"""
Complete command flow for creating a new aggregate instance.

This example demonstrates the full add-command workflow for a create operation:
- Command class with imperative naming (RegisterUser)
- Command handler that constructs a new aggregate from command data
- FastAPI POST endpoint that accepts a JSON payload and submits the command
- Domain context middleware for request handling
- Synchronous command processing with return value

Workflow:
    POST /users/register → RegisterUser command → UserCommandHandler
    → create User aggregate → persist → return user_id

Usage:
    curl -X POST http://localhost:8000/users/register \\
        -H "Content-Type: application/json" \\
        -d '{"user_id": "USR-001", "email": "alice@example.com", "name": "Alice"}'
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from protean import Domain, handle
from protean.fields import Identifier, String
from protean.utils.globals import current_domain

# Domain setup
domain = Domain()


@domain.aggregate
class User:
    """User aggregate representing a registered user."""

    user_id: Identifier(identifier=True)
    email: String(required=True, max_length=255)
    name: String(required=True, max_length=100)
    status: String(default="pending")

    def register(self):
        """Mark the user as registered."""
        self.status = "registered"

    def activate(self):
        """Activate the user account."""
        if self.status != "registered":
            raise ValueError(f"Cannot activate user in '{self.status}' status")
        self.status = "active"


# --- Command ---


@domain.command(part_of="User")
class RegisterUser:
    """Command expressing intent to register a new user.

    Named with imperative verb (Register) + noun (User).
    Associated with User aggregate via part_of string.
    """

    user_id: Identifier(required=True)
    email: String(required=True, max_length=255)
    name: String(required=True, max_length=100)


# --- Command Handler ---


@domain.command_handler(part_of=User)
class UserCommandHandler:
    """Handler for user-related commands.

    Associated with User aggregate via part_of class reference.
    Each @handle method processes one command type.
    Runs within an implicit UnitOfWork - no manual wrapping needed.
    """

    @handle(RegisterUser)
    def handle_register_user(self, command: RegisterUser):
        """Handle RegisterUser by creating a new User aggregate.

        Workflow:
        1. Construct aggregate from command data
        2. Call aggregate method to apply business logic
        3. Persist via repository
        4. Return identifier for the caller
        """
        user = User(
            user_id=command.user_id,
            email=command.email,
            name=command.name,
        )
        user.register()
        domain.repository_for(User).add(user)
        return user.user_id


# --- FastAPI Endpoint ---

app = FastAPI(title="User Registration API")


@app.middleware("http")
async def domain_context_middleware(request: Request, call_next):
    """Middleware to provide domain context for every request.

    Required so that current_domain is available in endpoint handlers.
    """
    with domain.domain_context():
        response = await call_next(request)
    return response


@app.post("/users/register", status_code=201)
async def register_user(request: Request):
    """Register a new user.

    This endpoint is a thin adapter:
    1. Extracts data from the HTTP request payload
    2. Constructs a RegisterUser command
    3. Submits it to the domain for synchronous processing
    4. Returns the result as a JSON response

    No business logic here - that lives in the aggregate.
    """
    payload = await request.json()

    command = RegisterUser(
        user_id=payload["user_id"],
        email=payload["email"],
        name=payload["name"],
    )

    result = current_domain.process(command, asynchronous=False)

    return JSONResponse(
        status_code=201,
        content={"user_id": result, "status": "registered"},
    )


# Example usage
if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    domain.init(traverse=False)
    uvicorn.run(app, host="127.0.0.1", port=8000)
