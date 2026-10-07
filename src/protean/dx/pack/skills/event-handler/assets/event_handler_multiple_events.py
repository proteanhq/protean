"""
Event handler with multiple @handle methods processing different event types.

This example demonstrates:
- A single event handler class with multiple @handle decorated methods
- Each method handles a different event type from the same aggregate
- Multiple events can be handled by one handler or spread across handlers
- The handler sits in Account's cluster (part_of=Account), the cluster that
  owns the events, and creates each Notification through a SendNotification
  command
- A redelivered event is a no-op: events are delivered at least once, so the
  command carries the event's message id as the notification id, and
  Notification's command handler skips one that already exists

Usage:
    account = Account(account_id="ACC-001", email="alice@example.com", name="Alice")
    domain.repository_for(Account).add(account)
    domain.process(RegisterAccount(account_id="ACC-001"))
    # AccountNotifier handles AccountRegistered event

    domain.process(SuspendAccount(account_id="ACC-001", reason="Suspicious activity"))
    # AccountNotifier handles AccountSuspended event
"""

from protean import Domain, current_domain, handle
from protean.exceptions import ObjectNotFoundError
from protean.fields import Identifier, String, Text

# Domain setup
domain = Domain()
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


@domain.command(part_of="Account")
class RegisterAccount:
    """Command to register an account."""

    account_id: Identifier(required=True)


@domain.command(part_of="Account")
class SuspendAccount:
    """Command to suspend an account."""

    account_id: Identifier(required=True)
    reason: String(required=True)


@domain.command(part_of="Account")
class ReactivateAccount:
    """Command to reactivate a suspended account."""

    account_id: Identifier(required=True)


@domain.command(part_of="Notification")
class SendNotification:
    """Command to create one notification.

    `notification_id` is the id of the event that caused it, so a redelivered
    event reissues the same command and the handler can tell it already ran.
    """

    notification_id: Identifier(required=True)
    account_id: Identifier(required=True)
    notification_type: String(required=True)
    message: Text(required=True)


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

    `notification_id` is set by the caller from the event that caused the
    notification, so one event produces at most one notification.
    """

    notification_id: Identifier(identifier=True)
    account_id: Identifier(required=True)
    notification_type: String(required=True)
    message: Text(required=True)


@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    """The write path for Account."""

    @handle(RegisterAccount)
    def register_account(self, command: RegisterAccount):
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.register()
        repo.add(account)

    @handle(SuspendAccount)
    def suspend_account(self, command: SuspendAccount):
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.suspend(reason=command.reason)
        repo.add(account)

    @handle(ReactivateAccount)
    def reactivate_account(self, command: ReactivateAccount):
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.reactivate()
        repo.add(account)


@domain.command_handler(part_of=Notification)
class NotificationCommandHandler:
    """The write path for Notification."""

    @handle(SendNotification)
    def send_notification(self, command: SendNotification):
        repo = current_domain.repository_for(Notification)
        try:
            repo.get(command.notification_id)
        except ObjectNotFoundError:
            repo.add(
                Notification(
                    notification_id=command.notification_id,
                    account_id=command.account_id,
                    notification_type=command.notification_type,
                    message=command.message,
                )
            )
        else:
            return  # already sent; a second one would notify the user twice


@domain.event_handler(part_of=Account)
class AccountNotifier:
    """Event handler that sends notifications for account events.

    This handler sits in Account's cluster because the events belong to
    Account. It reacts to each lifecycle event by issuing a SendNotification
    command, and Notification's command handler creates the record.

    Multiple @handle methods allow one handler to react to different
    event types from the same stream.

    `event._metadata.headers.id` is the event's message id, the same on
    every delivery of that event. An account can be suspended more than once,
    so the account id alone would not name one notification.
    It has the form `<stream>-<version>.<n>`, so it names one change only
    while the account is loaded fresh before each change, as the command
    handlers here do. An instance saved twice without reloading raises its
    second event under the same id.
    """

    @handle(AccountRegistered)
    def on_account_registered(self, event: AccountRegistered):
        """Handle AccountRegistered by sending a welcome notification."""
        current_domain.process(
            SendNotification(
                notification_id=event._metadata.headers.id,
                account_id=event.account_id,
                notification_type="welcome",
                message=f"Welcome {event.name}! Your account ({event.email}) "
                "is now active.",
            )
        )

    @handle(AccountSuspended)
    def on_account_suspended(self, event: AccountSuspended):
        """Handle AccountSuspended by sending a suspension notification."""
        current_domain.process(
            SendNotification(
                notification_id=event._metadata.headers.id,
                account_id=event.account_id,
                notification_type="suspension",
                message=f"Your account has been suspended. Reason: {event.reason}",
            )
        )

    @handle(AccountReactivated)
    def on_account_reactivated(self, event: AccountReactivated):
        """Handle AccountReactivated by sending a reactivation notification."""
        current_domain.process(
            SendNotification(
                notification_id=event._metadata.headers.id,
                account_id=event.account_id,
                notification_type="reactivation",
                message="Your account has been reactivated. Welcome back!",
            )
        )


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
        domain.repository_for(Account).add(account)
        domain.process(RegisterAccount(account_id="ACC-001"))
        print("Account registered - welcome notification sent")

        # Suspend the account
        domain.process(
            SuspendAccount(account_id="ACC-001", reason="Suspicious activity detected")
        )
        print("Account suspended - suspension notification sent")

        # Reactivate the account
        domain.process(ReactivateAccount(account_id="ACC-001"))
        print("Account reactivated - reactivation notification sent")

        notifications = domain.repository_for(Notification).query.all().items
        assert sorted(n.notification_type for n in notifications) == [
            "reactivation",
            "suspension",
            "welcome",
        ]
