from protean import (
    BaseEvent,
    BaseEventHandler,
    BaseEventSourcedAggregate,
    Domain,
    handle,
)
from protean.fields import Identifier, String
from tests.server.test_command_handling import UserCommandHandler

domain = Domain()


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class PasswordChanged(BaseEvent):
    id = Identifier()
    password_hash = String()


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
    email = String()
    name = String()
    password_hash = String()


def count_up():
    print("Counting...")


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def send_notification(self, event: Registered) -> None:
        count_up()

    @handle(PasswordChanged)
    def reset_token(self, event: PasswordChanged) -> None:
        pass


domain.register(User)
domain.register(UserCommandHandler, aggregate_cls=User)
domain.register(UserEventHandler, aggregate_cls=User)
