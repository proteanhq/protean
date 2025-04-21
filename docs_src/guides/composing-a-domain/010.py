from protean import Domain, handle
from protean.fields import Identifier, String

domain = Domain()


@domain.aggregate
class User:
    id = Identifier()
    email = String()
    name = String()


@domain.command(part_of=User)
class Register:
    id = Identifier()
    email = String()


@domain.event(part_of=User)
class Registered:
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


@domain.event_handler
class UserEventHandlers:
    @handle(Registered)
    def send_email_notification(self, event: Registered) -> None:
        pass
