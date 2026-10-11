from protean import Domain, handle
from protean.fields import String

domain = Domain(name="People")
domain.config["event_processing"] = "sync"


class Notifications:
    """Stands in for the application's own notification service."""

    def __init__(self):
        self.welcomed = []

    def send_welcome(self, to, name):
        self.welcomed.append((to, name))


notifications = Notifications()


# --8<-- [start:elements]
@domain.aggregate
class Person:
    first_name = String(required=True)
    email = String(required=True)


@domain.event(part_of=Person)
class PersonAdded:
    first_name = String(required=True)
    email = String(required=True)


# --8<-- [end:elements]


# --8<-- [start:handler]
@domain.event_handler(part_of=Person)
class SendWelcomeNotification:
    @handle(PersonAdded)
    def on_person_added(self, event: PersonAdded) -> None:
        # `notifications` is your application-level service wrapping whatever
        # email/SMS/push transport you use (SendGrid, SES, a queue, ...).
        notifications.send_welcome(to=event.email, name=event.first_name)


# --8<-- [end:handler]
