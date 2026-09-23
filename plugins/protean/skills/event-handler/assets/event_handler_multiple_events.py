"""
Event handler with multiple @handle methods processing different event types.

This example demonstrates:
- A single event handler class with multiple @handle decorated methods
- Each method handles a different event type from the same aggregate
- Multiple events can be handled by one handler or spread across handlers
- Event handlers update aggregate state in response to different domain events

Usage:
    account = Account(account_id="ACC-001", email="alice@example.com", name="Alice")
    account.register()
    domain.repository_for(Account).add(account)
    # AccountNotifier handles AccountRegistered event

    account.suspend(reason="Suspicious activity")
    domain.repository_for(Account).add(account)
    # AccountNotifier handles AccountSuspended event
"""

from protean import Domain, handle
from protean.fields import Identifier, String, Text

# Domain setup
domain = Domain()
domain.config["event_processing"] = "sync"


@domain.event(part_of="Account")
class AccountRegistered:
    """Event raised when a new account is registered."""

    account_id: Identifier(required=True)
    email: String(required=True)
    name: String(required=True)


@domain.event(part_of="Account")
class AccountSuspended:
    """Event raised when an account is suspended."""

    account_id: Identifier(required=True)
    reason: String(required=True)


@domain.event(part_of="Account")
class AccountReactivated:
    """Event raised when a suspended account is reactivated."""

    account_id: Identifier(required=True)


@domain.aggregate
class Account:
    """Account aggregate with multiple state transitions that raise events."""

    account_id: Identifier(identifier=True)
    email: String(required=True)
    name: String(required=True)
    status: String(default="pending")
    suspended_reason: String()

    def register(self):
        """Register the account, raising AccountRegistered event."""
        self.status = "active"
        self.raise_(
            AccountRegistered(
                account_id=self.account_id,
                email=self.email,
                name=self.name,
            )
        )

    def suspend(self, reason: str):
        """Suspend the account, raising AccountSuspended event."""
        if self.status != "active":
            raise ValueError(f"Cannot suspend account in '{self.status}' status")
        self.status = "suspended"
        self.suspended_reason = reason
        self.raise_(
            AccountSuspended(
                account_id=self.account_id,
                reason=reason,
            )
        )

    def reactivate(self):
        """Reactivate a suspended account, raising AccountReactivated event."""
        if self.status != "suspended":
            raise ValueError(f"Cannot reactivate account in '{self.status}' status")
        self.status = "active"
        self.suspended_reason = None
        self.raise_(AccountReactivated(account_id=self.account_id))


@domain.aggregate
class Notification:
    """Notification aggregate for tracking sent notifications.

    Uses the default auto-generated `id` field since notifications
    don't have a natural business identifier.
    """

    account_id: Identifier(required=True)
    notification_type: String(required=True)
    message: Text(required=True)


@domain.event_handler(
    part_of=Notification, stream_category=Account.meta_.stream_category
)
class AccountNotifier:
    """Event handler that sends notifications for account events.

    This handler listens to the Account aggregate's event stream
    (stream_category=Account.meta_.stream_category) and creates
    Notification records for important account lifecycle events.

    Multiple @handle methods allow one handler to react to different
    event types from the same stream.
    """

    @handle(AccountRegistered)
    def on_account_registered(self, event: AccountRegistered):
        """Handle AccountRegistered by creating a welcome notification."""
        notification = Notification(
            account_id=event.account_id,
            notification_type="welcome",
            message=f"Welcome {event.name}! Your account ({event.email}) is now active.",
        )
        domain.repository_for(Notification).add(notification)

    @handle(AccountSuspended)
    def on_account_suspended(self, event: AccountSuspended):
        """Handle AccountSuspended by creating a suspension notification."""
        notification = Notification(
            account_id=event.account_id,
            notification_type="suspension",
            message=f"Your account has been suspended. Reason: {event.reason}",
        )
        domain.repository_for(Notification).add(notification)

    @handle(AccountReactivated)
    def on_account_reactivated(self, event: AccountReactivated):
        """Handle AccountReactivated by creating a reactivation notification."""
        notification = Notification(
            account_id=event.account_id,
            notification_type="reactivation",
            message="Your account has been reactivated. Welcome back!",
        )
        domain.repository_for(Notification).add(notification)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Register an account
        account = Account(
            account_id="ACC-001",
            email="alice@example.com",
            name="Alice Smith",
        )
        account.register()
        domain.repository_for(Account).add(account)
        print("Account registered - welcome notification sent")

        # Suspend the account
        account.suspend(reason="Suspicious activity detected")
        domain.repository_for(Account).add(account)
        print("Account suspended - suspension notification sent")

        # Reactivate the account
        account.reactivate()
        domain.repository_for(Account).add(account)
        print("Account reactivated - reactivation notification sent")
