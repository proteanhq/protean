"""
Handler integration testing scaffold: Command → Handler → Aggregate → Event → API.

This example demonstrates:
- Command processing via domain.process()
- Command handler orchestration (create aggregate, call method, persist)
- Aggregate factory method with event raising
- User-defined state transition business rules
- FastAPI endpoint integration
- Pytest tests for the handler and the endpoint, run with the fixtures in
  conftest.py, which set command and event processing to "sync"

The endpoint tests use FastAPI's TestClient, which needs the `fastapi` and
`httpx` packages. A project without FastAPI keeps only the handler tests.

Domain: A user registration system where RegisterUser command creates
a User aggregate, calls register() to set status and raise UserRegistered,
then persists. A FastAPI endpoint wires HTTP to the command.
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from protean import Domain, handle
from protean.fields import Identifier, String
from protean.utils.globals import current_domain

domain = Domain()


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
    result = current_domain.process(command)
    return JSONResponse(
        status_code=201,
        content={"user_id": str(result), "status": "registered"},
    )


# --- Tests ---


class TestUser:
    def test_register_raises_user_registered(self):
        user = User.register(email="a@test.com", name="Alice")
        assert user.status == "registered"
        assert len(user._events) == 1
        event = user._events[0]
        assert isinstance(event, UserRegistered)
        assert event.user_id == user.id
        assert event.email == "a@test.com"

    def test_activate_a_registered_user(self):
        user = User.register(email="a@test.com", name="Alice")
        user.activate()
        assert user.status == "active"

    def test_cannot_activate_a_pending_user(self):
        # activate() raises ValueError for a user that is not registered.
        user = User(email="a@test.com", name="Alice")
        with pytest.raises(ValueError, match="Cannot activate user in 'pending' status"):
            user.activate()


class TestHandlerProcessing:
    def test_register_user_creates_and_persists(self):
        # command_processing is "sync", so process() runs the handler now and
        # returns its result.
        result = domain.process(RegisterUser(email="a@test.com", name="Alice"))

        user = domain.repository_for(User).get(result)
        assert user.status == "registered"
        assert user.email == "a@test.com"

    def test_each_command_creates_its_own_user(self):
        first = domain.process(RegisterUser(email="a@test.com", name="A"))
        second = domain.process(RegisterUser(email="b@test.com", name="B"))

        assert first != second
        assert domain.repository_for(User).get(second).email == "b@test.com"


class TestRegisterEndpoint:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_register_returns_201_and_persists(self, client):
        response = client.post(
            "/users/register", json={"email": "a@test.com", "name": "Alice"}
        )

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "registered"
        user = domain.repository_for(User).get(data["user_id"])
        assert user.name == "Alice"
