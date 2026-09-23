"""
Basic use case: Command → Command Handler → Aggregate → Event.

This example demonstrates:
- Defining a command with required fields
- Aggregate factory method that creates and raises event
- Command handler that dispatches to aggregate
- Synchronous command processing via domain.process()
- End-to-end flow for a "Register Account" use case

Domain: A user registration system where RegisterAccount command
creates an Account aggregate and raises AccountRegistered event.
"""

from protean import Domain, handle
from protean.fields import Identifier, String

domain = Domain(__name__)


# --- Events ---


@domain.event(part_of="Account")
class AccountRegistered:
    """Raised when a new account is registered."""

    account_id: Identifier(required=True)
    username: String(required=True)
    email: String(required=True)


# --- Aggregate ---


@domain.aggregate
class Account:
    """Account aggregate for user registration."""

    username: String(required=True, max_length=50)
    email: String(required=True, max_length=200)
    status: String(default="active")

    @classmethod
    def register(cls, username, email):
        """Factory method: register a new account and raise event."""
        account = cls(username=username, email=email)
        account.raise_(
            AccountRegistered(
                account_id=account.id,
                username=account.username,
                email=account.email,
            )
        )
        return account


# --- Command ---


@domain.command(part_of="Account")
class RegisterAccount:
    """Command to register a new account."""

    username: String(required=True, max_length=50)
    email: String(required=True, max_length=200)


# --- Command Handler ---


@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    """Handles account-related commands."""

    @handle(RegisterAccount)
    def handle_register(self, command: RegisterAccount):
        """Handle RegisterAccount: create account and persist."""
        account = Account.register(
            username=command.username,
            email=command.email,
        )
        domain.repository_for(Account).add(account)
