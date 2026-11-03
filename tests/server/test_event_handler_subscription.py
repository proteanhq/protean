import asyncio

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import DateTime, Identifier, String
from protean.server import Engine
from protean.utils import fqn
from protean.utils.mixins import handle


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class Activated(BaseEvent):
    id = Identifier()
    activated_at = DateTime()


class Sent(BaseEvent):
    email = String()
    sent_on = DateTime()


class User(BaseAggregate):
    email = String()
    name = String()
    password_hash = String()


def dummy(*args):
    pass


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def send_activation_email(self, event: Registered) -> None:
        dummy(event)

    @handle(Activated)
    def provision_user(self, event: Activated) -> None:
        dummy(event)

    @handle(Activated)
    def send_welcome_email(self, event: Activated) -> None:
        dummy(event)


class EmailEventHandler(BaseEventHandler):
    @handle(Sent)
    def record_sent_email(self, event: Sent) -> None:
        pass


@pytest.fixture(autouse=True)
def setup_event_loop():
    """Ensure an Event Loop Exists in Tests.

    Otherwise tests are attempting to access the asyncio event loop from a non-async context
    where no event loop is running or set as the current event loop.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    loop.close()
    asyncio.set_event_loop(None)


@pytest.mark.parametrize(
    "handler, events, options, stream_category, origin_stream",
    [
        (UserEventHandler, [Registered, Activated], {}, "test::user", None),
        (
            EmailEventHandler,
            [Sent],
            {"source_stream": "test::email"},
            "test::user",
            "test::email",
        ),
        (
            EmailEventHandler,
            [Sent],
            {"stream_category": "test::identity", "source_stream": "test::email"},
            "test::identity",
            "test::email",
        ),
    ],
    ids=["derived_from_aggregate", "source_stream", "stream_category_override"],
)
def test_event_handler_subscription(
    test_domain, handler, events, options, stream_category, origin_stream
):
    """The engine creates one subscription per event handler, on the stream
    derived from the owning aggregate unless stream_category overrides it,
    with source_stream as the origin stream."""
    test_domain.register(User, event_sourced=True)
    for event in events:
        test_domain.register(event, part_of=User)
    test_domain.register(handler, part_of=User, **options)
    test_domain.init(traverse=False)

    engine = Engine(test_domain, test_mode=True)

    assert list(engine._subscriptions) == [fqn(handler)]
    subscription = engine._subscriptions[fqn(handler)]
    assert subscription.stream_category == stream_category
    assert subscription.origin_stream == origin_stream
