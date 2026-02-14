import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.fields import Identifier, String
from protean.server import Engine
from protean.utils import fully_qualified_name
from protean.utils.mixins import handle


class User(BaseAggregate):
    id: Identifier(identifier=True)
    email: String()
    name: String()


class Register(BaseCommand):
    user_id: Identifier()
    email: String()


class Activate(BaseCommand):
    user_id: Identifier()


def dummy(*args):
    pass


class UserCommandHandler(BaseCommandHandler):
    @handle(Register)
    def register(self, command: Register) -> None:
        dummy(self, command)

    @handle(Activate)
    def activate(self, command: Activate) -> None:
        dummy(self, command)


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.register(Activate, part_of=User)
    test_domain.register(UserCommandHandler, part_of=User)
    test_domain.init(traverse=False)


@pytest.fixture
def engine(test_domain):
    return Engine(test_domain, test_mode=True)


def test_command_handler_subscriptions(engine):
    assert len(engine._subscriptions) == 1

    assert fully_qualified_name(UserCommandHandler) in engine._subscriptions
    assert (
        engine._subscriptions[fully_qualified_name(UserCommandHandler)].stream_category
        == "test::user:command"
    )
