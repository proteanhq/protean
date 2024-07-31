from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.exceptions import ConfigurationError
from protean.fields import Identifier, String
from protean.utils import Processing
from protean.utils.mixins import handle

counter = 0


class User(BaseAggregate):
    user_id = Identifier(identifier=True)
    email = String()
    name = String()


class Register(BaseCommand):
    user_id = Identifier(identifier=True)
    email = String()


class Login(BaseCommand):
    user_id = Identifier()


class UserCommandHandlers(BaseCommandHandler):
    @handle(Register)
    def register(self, event: Register) -> None:
        global counter
        counter += 1


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User)
    test_domain.register(Register, part_of=User)
    test_domain.register(UserCommandHandlers, part_of=User)
    test_domain.init(traverse=False)


def test_unregistered_command_raises_error(test_domain):
    with pytest.raises(ConfigurationError):
        test_domain.process(Login(user_id=str(uuid4())))


def test_that_command_can_be_processed_inline(test_domain):
    test_domain.register(User)
    test_domain.register(Register, part_of=User)
    test_domain.register(UserCommandHandlers, part_of=User)
    test_domain.init(traverse=False)

    assert test_domain.config["command_processing"] == Processing.SYNC.value

    test_domain.process(Register(user_id=str(uuid4()), email="john.doe@gmail.com"))
    assert counter == 1


def test_that_command_is_persisted_in_message_store(test_domain):
    identifier = str(uuid4())
    test_domain.process(Register(user_id=identifier, email="john.doe@gmail.com"))

    messages = test_domain.event_store.store.read("user:command")

    assert len(messages) == 1
    assert messages[0].stream_name == f"test::user:command-{identifier}"
