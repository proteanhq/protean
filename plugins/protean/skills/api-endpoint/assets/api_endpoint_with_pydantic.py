"""
Endpoints with Pydantic request models.

This example demonstrates:
- Pydantic models as FastAPI request bodies
- Two kinds of rejected input, with two status codes:
  - FastAPI returns 422 with a ``detail`` list when the body does not match
    the Pydantic model (a missing key, a wrong type, a failed ``pattern``)
  - Protean returns 400 with ``{"error": {"<field>": [...]}}`` when the
    command's own fields reject a value the model let through (here, a name
    longer than ``max_length``)
- Mapping the validated model fields to command fields, one by one
- Pydantic checks the shape of the request; the command and the aggregate
  enforce the domain rules

This file holds the router only. Build the app the way the ``create_app``
factory in ``api_endpoint_complete_router.py`` does, and include this router.
Pass the factory this file's ``domain``, which registers the router's commands.

Usage, once the app is running:
    # POST /accounts/register with a valid payload
    curl -X POST http://localhost:8000/accounts/register \\
        -H "Content-Type: application/json" \\
        -d '{"account_id": "ACC-001", "email": "alice@example.com", "name": "Alice"}'

    # An invalid email fails the Pydantic model: 422
    curl -X POST http://localhost:8000/accounts/register \\
        -H "Content-Type: application/json" \\
        -d '{"account_id": "ACC-001", "email": "not-an-email", "name": "Alice"}'
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from protean import Domain, handle
from protean.exceptions import InvalidStateError
from protean.fields import Identifier, String
from protean.utils.globals import current_domain

domain = Domain()


@domain.aggregate
class Account:
    """Account aggregate."""

    account_id: Identifier(identifier=True)
    email: String(required=True)
    name: String(required=True, max_length=50)
    status: String(default="pending")

    def activate(self):
        """Activate a pending account."""
        if self.status != "pending":
            raise InvalidStateError(
                f"Cannot activate account in '{self.status}' status"
            )
        self.status = "active"


@domain.command(part_of="Account")
class RegisterAccount:
    """Command to register a new account."""

    account_id: Identifier(required=True)
    email: String(required=True)
    name: String(required=True, max_length=50)


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
        current_domain.repository_for(Account).add(account)
        return account.account_id

    @handle(ActivateAccount)
    def handle_activate(self, command: ActivateAccount):
        """Activate a pending account."""
        account = current_domain.repository_for(Account).get(command.account_id)
        account.activate()
        current_domain.repository_for(Account).add(account)
        return account.account_id


# --- Pydantic request models ---


class RegisterAccountRequest(BaseModel):
    """The shape of a registration request.

    FastAPI checks the body against this model before the endpoint runs and
    returns 422 when it does not match. The model checks format only. The
    name's length limit is a domain rule, so it lives on the command.
    """

    account_id: str = Field(..., min_length=1, description="Unique account identifier")
    email: str = Field(
        ..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", description="Valid email address"
    )
    name: str = Field(..., min_length=1, description="Account holder name")


class ActivateAccountRequest(BaseModel):
    """The shape of an activation request."""

    account_id: str = Field(..., min_length=1, description="Account to activate")


router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post("/register", status_code=201)
def register_account(body: RegisterAccountRequest):
    """Register a new account from a validated request body."""
    command = RegisterAccount(
        account_id=body.account_id,
        email=body.email,
        name=body.name,
    )
    result = current_domain.process(command, asynchronous=False)
    return {"account_id": result, "status": "registered"}


@router.post("/activate")
def activate_account(body: ActivateAccountRequest):
    """Activate an existing account."""
    command = ActivateAccount(account_id=body.account_id)
    result = current_domain.process(command, asynchronous=False)
    return {"account_id": result, "status": "activated"}
