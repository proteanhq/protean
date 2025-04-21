from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.fields import Identifier, String
from protean.server import Engine
from protean.utils import Processing
from protean.utils.mixins import Message, handle

counter = 0


class User(BaseAggregate):
    id = Identifier(identifier=True)
    email = String()
    name = String()


class Register(BaseCommand):
    user_id = Identifier()
    email = String()


class Activate(BaseCommand):
    user_id = Identifier()


def dummy(*args):
    global counter
    counter += 1


class UserCommandHandler(BaseCommandHandler):
    @handle(Register)
    def register(self, command: Register) -> None:
        dummy(command)

    @handle(Activate)
    def activate(self, command: Activate) -> None:
        dummy(command)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.register(Activate, part_of=User)
    test_domain.register(UserCommandHandler, part_of=User)
    test_domain.init(traverse=False)


@pytest.fixture(autouse=True)
def reset_counter():
    """Reset the counter before each test."""
    global counter
    counter = 0

    yield


@pytest.mark.asyncio
async def test_handler_invocation(test_domain):
    identifier = str(uuid4())
    command = Register(
        user_id=identifier,
        email="john.doe@example.com",
    )
    enriched_command = test_domain._enrich_command(command, True)
    message = Message.to_message(enriched_command)

    engine = Engine(domain=test_domain, test_mode=True)
    await engine.handle_message(UserCommandHandler, message)

    global counter
    assert counter == 1


def test_synchronous_command_is_not_handled_asynchronously(test_domain):
    test_domain.config["command_processing"] = Processing.SYNC.value

    identifier = str(uuid4())
    command = Register(
        user_id=identifier,
        email="john.doe@example.com",
    )
    test_domain.process(command)

    messages = test_domain.event_store.store.read("test::user:command")
    assert len(messages) == 1

    engine = Engine(domain=test_domain, test_mode=True)
    engine.run()

    global counter
    assert counter == 1
