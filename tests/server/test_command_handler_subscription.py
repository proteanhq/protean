from uuid import uuid4

import mock

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


def dummy(*args):
    pass


class UserCommandHandler(BaseCommandHandler):
    @handle(Register)
    def register(self, command: Register) -> None:
        dummy(self, command)

    class Meta:
        aggregate_cls = User


def test_subscriptions_to_event_handler(test_domain):
    test_domain.register(UserCommandHandler, aggregate_cls=User)

    engine = Engine(test_domain, test_mode=True)
    assert len(engine._command_subscriptions) == 1
    assert fully_qualified_name(UserCommandHandler) in engine._command_subscriptions
    assert (
        engine._command_subscriptions[
            fully_qualified_name(UserCommandHandler)
        ].stream_name
        == "user:command"
    )


@mock.patch("tests.server.test_command_handler_subscription.dummy")
def test_call_to_event_handler(mock_dummy, test_domain):
    test_domain.register(UserCommandHandler, aggregate_cls=User)

    identifier = str(uuid4())
    test_domain.event_store.store._write(
        f"user:command-{identifier}",
        fully_qualified_name(Register),
        Register(
            user_id=identifier,
            email="john.doe@gmail.com",
        ).to_dict(),
    )

    engine = Engine(test_domain, test_mode=True)
    engine.run()

    mock_dummy.assert_called_once()  # FIXME Verify content
