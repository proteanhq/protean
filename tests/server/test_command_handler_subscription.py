import pytest

from protean import BaseCommand, BaseCommandHandler, BaseEventSourcedAggregate, handle
from protean.fields import Identifier, String
from protean.server import Engine
from protean.utils import fully_qualified_name


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
    test_domain.register(UserCommandHandler, aggregate_cls=User)


@pytest.fixture
def engine(test_domain):
    return Engine(test_domain, test_mode=True)


def test_command_handler_subscriptions(engine):
    assert len(engine._subscriptions) == 1

    assert fully_qualified_name(UserCommandHandler) in engine._subscriptions
    assert (
        engine._subscriptions[fully_qualified_name(UserCommandHandler)].stream_name
        == "user:command"
    )
