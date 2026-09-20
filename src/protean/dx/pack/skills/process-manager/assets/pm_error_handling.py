"""
Process manager with custom error handling via handle_error classmethod.

This example demonstrates:
- The optional handle_error classmethod for custom error recovery
- How the Protean Engine calls handle_error when PM processing fails
- Error logging pattern for process managers
- The handle_error method signature: cls, exc, message

Note: handle_error is called by the Protean Engine during asynchronous
processing. In synchronous mode, exceptions propagate directly.

Domain: User onboarding process
    - AccountCreated (start) -> status: awaiting_verification
    - EmailVerified (mark_as_complete) -> status: verified

Usage:
    from pm_error_handling import OnboardingPM, domain

    domain.init(traverse=False)
    with domain.domain_context():
        pm = OnboardingPM(account_id="ACC-001", status="new")
"""

import logging

from protean import Domain, handle
from protean.fields import Identifier, String

# Domain setup
domain = Domain(__file__, "onboarding")

logger = logging.getLogger(__name__)


# --- Events ---


@domain.event(part_of="Account")
class AccountCreated:
    """Raised when a new user account is created."""

    account_id: Identifier(required=True)
    email: String(required=True)


@domain.event(part_of="Account")
class EmailVerified:
    """Raised when the user's email address is verified."""

    account_id: Identifier(required=True)


# --- Aggregate ---


@domain.aggregate
class Account:
    """Account aggregate representing a user account."""

    email: String(required=True)
    status: String(default="pending")


# --- Process Manager ---


@domain.process_manager(stream_categories=["onboarding::account"])
class OnboardingPM:
    """Manages the user onboarding process with custom error handling.

    The handle_error classmethod provides a hook for logging, notification,
    or recovery logic when event processing fails during async operation.
    """

    account_id: Identifier()
    status: String(default="new")

    @handle(AccountCreated, start=True, correlate="account_id")
    def on_account_created(self, event: AccountCreated) -> None:
        """Start onboarding when a new account is created."""
        self.account_id = event.account_id
        self.status = "awaiting_verification"

    @handle(EmailVerified, correlate="account_id")
    def on_email_verified(self, event: EmailVerified) -> None:
        """Complete onboarding when email is verified."""
        self.status = "verified"
        self.mark_as_complete()

    @classmethod
    def handle_error(cls, exc: Exception, message) -> None:
        """Custom error handling for failed onboarding event processing.

        Called by the Protean Engine when an exception occurs during
        asynchronous event processing. Use for logging, alerting,
        or triggering compensating actions.

        Args:
            exc: The exception that was raised during handling.
            message: The original event message that was being processed.
        """
        logger.error(
            "Onboarding PM event processing failed: %s (type: %s)",
            str(exc),
            type(exc).__name__,
        )
