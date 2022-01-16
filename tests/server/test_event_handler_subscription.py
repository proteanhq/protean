from __future__ import annotations

from protean import BaseEvent, BaseEventHandler, BaseEventSourcedAggregate, handle
from protean.fields import DateTime, Identifier, String
from protean.server import Engine
from protean.utils import fqn


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


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
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


def test_event_subscriptions(test_domain):
    test_domain.register(UserEventHandler, aggregate_cls=User)
    engine = Engine(test_domain, test_mode=True)

    assert len(engine._subscriptions) == 1
    assert fqn(UserEventHandler) in engine._subscriptions
    assert engine._subscriptions[fqn(UserEventHandler)].stream_name == "user"


def test_origin_stream_name_in_subscription(test_domain):
    test_domain.register(EmailEventHandler, aggregate_cls=User, source_stream="email")

    engine = Engine(test_domain, test_mode=True)

    assert len(engine._subscriptions) == 1
    assert engine._subscriptions[fqn(EmailEventHandler)].stream_name == "user"
    assert engine._subscriptions[fqn(EmailEventHandler)].origin_stream_name == "email"


def test_that_stream_name_overrides_the_derived_stream_name_from_aggregate_cls(
    test_domain,
):
    test_domain.register(
        EmailEventHandler,
        aggregate_cls=User,
        stream_name="identity",
        source_stream="email",
    )

    engine = Engine(test_domain, test_mode=True)

    assert len(engine._subscriptions) == 1
    assert engine._subscriptions[fqn(EmailEventHandler)].stream_name == "identity"
    assert engine._subscriptions[fqn(EmailEventHandler)].origin_stream_name == "email"
