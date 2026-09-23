"""
Endpoint with Pydantic request model for input validation.

This example demonstrates:
- Using Pydantic models for FastAPI request body validation
- FastAPI's automatic 422 response for invalid payloads
- Mapping validated Pydantic model fields to Protean command fields
- Clear separation: Pydantic validates HTTP input, Protean commands carry domain intent
- POST endpoint for account registration with validated fields

Usage:
    # Start the server
    python api_endpoint_with_pydantic.py

    # POST /accounts/register with validated payload
    curl -X POST http://localhost:8000/accounts/register \\
        -H "Content-Type: application/json" \\
        -d '{"account_id": "ACC-001", "email": "alice@example.com", "name": "Alice"}'

    # Invalid email triggers 422
    curl -X POST http://localhost:8000/accounts/register \\
        -H "Content-Type: application/json" \\
        -d '{"account_id": "ACC-001", "email": "not-an-email", "name": "Alice"}'
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from protean import Domain, handle
from protean.fields import Identifier, String
from protean.utils.globals import current_domain

# Domain setup
domain = Domain()


@domain.aggregate
class Account:
    """Account aggregate."""

    account_id: Identifier(identifier=True)
    email: String(required=True)
    name: String(required=True)
    status: String(default="pending")

    def activate(self):
        """Activate a pending account."""
        if self.status != "pending":
            raise ValueError(f"Cannot activate account in '{self.status}' status")
        self.status = "active"


@domain.command(part_of="Account")
class RegisterAccount:
    """Command to register a new account."""

    account_id: Identifier(required=True)
    email: String(required=True)
    name: String(required=True)


@domain.command(part_of="Account")
class ActivateAccount:
    """Command to activate a pending account."""

    account_id: Identifier(required=True)


@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    """Handler for account commands."""

    @handle(RegisterAccount)
    def handle_register(self, command: RegisterAccount):
        """Register a new account."""
        account = Account(
            account_id=command.account_id,
            email=command.email,
            name=command.name,
        )
        domain.repository_for(Account).add(account)
        return account.account_id

    @handle(ActivateAccount)
    def handle_activate(self, command: ActivateAccount):
        """Activate a pending account."""
        account = domain.repository_for(Account).get(command.account_id)
        account.activate()
        domain.repository_for(Account).add(account)
        return account.account_id


# --- Pydantic request models for FastAPI validation ---


class RegisterAccountRequest(BaseModel):
    """Pydantic model for validating registration requests.

    This model validates the HTTP request body BEFORE
    constructing the Protean command. FastAPI returns 422
    automatically if validation fails.
    """

    account_id: str = Field(..., min_length=1, description="Unique account identifier")
    email: str = Field(
        ..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", description="Valid email address"
    )
    name: str = Field(
        ..., min_length=1, max_length=100, description="Account holder name"
    )


class ActivateAccountRequest(BaseModel):
    """Pydantic model for validating activation requests."""

    account_id: str = Field(..., min_length=1, description="Account to activate")


# FastAPI app setup
app = FastAPI(title="Pydantic Validation Endpoint Example")


@app.middleware("http")
async def domain_context_middleware(request: Request, call_next):
    """Middleware to provide domain context for every request."""
    with domain.domain_context():
        response = await call_next(request)
    return response


@app.post("/accounts/register", status_code=201)
async def register_account(body: RegisterAccountRequest):
    """Register a new account.

    FastAPI validates the request body against RegisterAccountRequest.
    If validation passes, the endpoint constructs a RegisterAccount
    command from the validated data and processes it via the domain.
    """
    command = RegisterAccount(
        account_id=body.account_id,
        email=body.email,
        name=body.name,
    )

    result = current_domain.process(command, asynchronous=False)

    return JSONResponse(
        status_code=201,
        content={"account_id": result, "status": "registered"},
    )


@app.post("/accounts/activate")
async def activate_account(body: ActivateAccountRequest):
    """Activate an existing account.

    Uses Pydantic validation for the request body, then constructs
    an ActivateAccount command for domain processing.
    """
    command = ActivateAccount(
        account_id=body.account_id,
    )

    result = current_domain.process(command, asynchronous=False)

    return JSONResponse(
        content={"account_id": result, "status": "activated"},
    )


# Example usage
if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    domain.init(traverse=False)
    uvicorn.run(app, host="127.0.0.1", port=8000)
