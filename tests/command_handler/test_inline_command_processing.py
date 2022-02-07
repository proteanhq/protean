from uuid import uuid4

from protean import BaseAggregate, BaseCommand, handle
from protean.core.command_handler import BaseCommandHandler
from protean.fields import Identifier, String
from protean.utils import CommandProcessing

counter = 0


class User(BaseAggregate):
    user_id = Identifier(identifier=True)
    email = String()
    name = String()


class Register(BaseCommand):
    user_id = Identifier()
    email = String()

    class Meta:
        aggregate_cls = User


class UserCommandHandlers(BaseCommandHandler):
    @handle(Register)
    def register(self, event: Register) -> None:
        global counter
        counter += 1


def test_that_a_handler_is_recorded_against_command_handler(test_domain):
    test_domain.register(User)
    test_domain.register(UserCommandHandlers, aggregate_cls=User)

    assert test_domain.config["COMMAND_PROCESSING"] == CommandProcessing.SYNC.value

    test_domain.process(Register(user_id=str(uuid4()), email="john.doe@gmail.com"))
    assert counter == 1
