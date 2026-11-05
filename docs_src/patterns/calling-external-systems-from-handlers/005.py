from protean import Domain, current_domain, handle
from protean.fields import Identifier, String

domain = Domain(name="Notifications")
domain.config["command_processing"] = "sync"
domain.config["event_processing"] = "sync"


class Outcome:
    def __init__(self, ok: bool) -> None:
        self.ok = ok


class Channel:
    def send(self, recipient: str, body: str) -> Outcome:
        raise NotImplementedError("Connect a real channel, such as an email provider")


channel = Channel()


# --8<-- [start:model]
@domain.event(part_of="Notification")
class NotificationDispatchStarted:
    notification_id: Identifier(required=True)
    recipient: String(required=True)
    body: String(required=True)


@domain.command(part_of="Notification")
class RecordDispatchResult:
    notification_id: Identifier(identifier=True)
    status: String(required=True)


@domain.aggregate
class Notification:
    notification_id: Identifier(identifier=True)
    recipient: String(required=True)
    body: String(required=True)
    status: String(default="PENDING")

    def start_dispatch(self):
        self.status = "DISPATCHING"
        self.raise_(
            NotificationDispatchStarted(
                notification_id=self.notification_id,
                recipient=self.recipient,
                body=self.body,
            )
        )

    def record_result(self, status):
        self.status = status


@domain.command_handler(part_of=Notification)
class NotificationCommandHandler:
    @handle(RecordDispatchResult)
    def record_result(self, command):
        repo = current_domain.repository_for(Notification)
        notification = repo.get(command.notification_id)
        notification.record_result(command.status)
        repo.add(notification)


# --8<-- [end:model]


# --8<-- [start:dispatch]
@domain.event_handler(part_of=Notification)
class NotificationDispatcher:
    @handle(NotificationDispatchStarted)
    def send(self, event):
        # The channel call reaches no repository.
        outcome = channel.send(event.recipient, event.body)
        current_domain.process(
            RecordDispatchResult(
                notification_id=event.notification_id,
                status="SENT" if outcome.ok else "FAILED",
            ),
            asynchronous=True,
        )


# --8<-- [end:dispatch]
