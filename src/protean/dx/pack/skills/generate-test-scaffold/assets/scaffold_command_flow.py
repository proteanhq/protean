"""
Handler integration testing scaffold: Command → Handler → Aggregate → Event → API.

This example demonstrates:
- Command processing via domain.process()
- Command handler orchestration (create aggregate, call method, persist)
- Aggregate factory method with event raising
- User-defined state transition business rules
- FastAPI endpoint integration
- Synchronous command processing for testability

Domain: A user registration system where RegisterUser command creates
a User aggregate, calls register() to set status and raise UserRegistered,
then persists. A FastAPI endpoint wires HTTP to the command.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from protean import Domain, handle
from protean.fields import Identifier, String
from protean.utils.globals import current_domain

domain = Domain(__name__)
domain.config["event_processing"] = "sync"


# --- Events ---


@domain.event(part_of="User")
class UserRegistered:
    """Raised when a new user is registered."""

    user_id: Identifier(required=True)
    email: String(required=True)
    name: String(required=True)


# --- Aggregate ---


@domain.aggregate
class User:
    """User aggregate with registration and activation logic."""

    email: String(required=True, max_length=255)
    name: String(required=True, max_length=100)
    status: String(default="pending")

    @classmethod
    def register(cls, email, name):
        """Factory: register a new user and raise UserRegistered event."""
        user = cls(email=email, name=name, status="registered")
        user.raise_(
            UserRegistered(
                user_id=user.id,
                email=user.email,
                name=user.name,
            )
        )
        return user

    def activate(self):
        """Activate the user. Only registered users can be activated."""
        if self.status != "registered":
            raise ValueError(f"Cannot activate user in '{self.status}' status")
        self.status = "active"


# --- Command ---


@domain.command(part_of="User")
class RegisterUser:
    """Command to register a new user."""

    email: String(required=True, max_length=255)
    name: String(required=True, max_length=100)


# --- Command Handler ---


@domain.command_handler(part_of=User)
class UserCommandHandler:
    """Handles user-related commands."""

    @handle(RegisterUser)
    def handle_register(self, command: RegisterUser):
        """Handle RegisterUser: create user via factory, persist, return ID."""
        user = User.register(email=command.email, name=command.name)
        domain.repository_for(User).add(user)
        return user.id


# --- FastAPI Endpoint ---

app = FastAPI(title="User Registration API")


@app.middleware("http")
async def domain_context_middleware(request: Request, call_next):
    """Provide domain context for every request."""
    with domain.domain_context():
        response = await call_next(request)
    return response


@app.post("/users/register", status_code=201)
async def register_user(request: Request):
    """Register a new user via HTTP.

    Thin adapter: extract payload → build command → process → return result.
    No business logic here.
    """
    payload = await request.json()
    command = RegisterUser(
        email=payload["email"],
        name=payload["name"],
    )
    result = current_domain.process(command, asynchronous=False)
    return JSONResponse(
        status_code=201,
        content={"user_id": str(result), "status": "registered"},
    )
