from uuid import uuid4

import pytest

from protean import BaseCommand, BaseCommandHandler, BaseEventSourcedAggregate, handle
from protean.fields import Identifier, String
from protean.server import Engine
from protean.utils.mixins import Message

counter = 0


class User(BaseEventSourcedAggregate):
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


@pytest.mark.asyncio
async def test_handler_invocation(test_domain):
    test_domain.register(User)
    test_domain.register(Register, part_of=User)
    test_domain.register(Activate, part_of=User)
    test_domain.register(UserCommandHandler, part_of=User)
    test_domain.init(traverse=False)

    identifier = str(uuid4())
    command = Register(
        user_id=identifier,
        email="john.doe@example.com",
    )
    enriched_command = test_domain._enrich_command(command)
    message = Message.to_message(enriched_command)

    engine = Engine(domain=test_domain, test_mode=True)
    await engine.handle_message(UserCommandHandler, message)

    global counter
    assert counter == 1
