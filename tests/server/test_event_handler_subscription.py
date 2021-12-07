from __future__ import annotations

from uuid import uuid4

import mock

from protean import BaseEvent, BaseEventHandler, BaseEventSourcedAggregate, handle
from protean.fields import Identifier, String
from protean.server import Engine
from protean.utils import fully_qualified_name


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
    email = String()
    name = String()
    password_hash = String()


def dummy(*args):
    pass


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def send_notification(self, event: Registered) -> None:
        dummy(event)


def test_subscriptions_to_event_handler(test_domain):
    test_domain.register(UserEventHandler, aggregate_cls=User)

    engine = Engine(test_domain, test_mode=True)
    assert len(engine._event_subscriptions) == 1
    assert fully_qualified_name(UserEventHandler) in engine._event_subscriptions
    assert (
        engine._event_subscriptions[fully_qualified_name(UserEventHandler)].stream_name
        == "user"
    )


@mock.patch("tests.server.test_event_handler_subscription.dummy")
def test_call_to_event_handler(mock_dummy, test_domain):
    test_domain.register(UserEventHandler, aggregate_cls=User)

    identifier = str(uuid4())
    test_domain.event_store.store._write(
        f"user-{identifier}",
        fully_qualified_name(Registered),
        Registered(
            id=identifier,
            email="john.doe@gmail.com",
            name="John Doe",
            password_hash="hash",
        ).to_dict(),
    )

    engine = Engine(test_domain, test_mode=True)
    engine.run()

    mock_dummy.assert_called_once()  # FIXME Verify content
