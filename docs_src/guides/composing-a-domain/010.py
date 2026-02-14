from protean import Domain, handle

domain = Domain()


@domain.aggregate
class User:
    id: str | None = None
    email: str | None = None
    name: str | None = None


@domain.command(part_of=User)
class Register:
    id: str | None = None
    email: str | None = None


@domain.event(part_of=User)
class Registered:
    id: str | None = None
    email: str | None = None
    name: str | None = None
    password_hash: str | None = None


@domain.event_handler(part_of=User)
class UserEventHandlers:
    @handle(Registered)
    def send_email_notification(self, event: Registered) -> None:
        pass
