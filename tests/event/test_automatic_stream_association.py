from __future__ import annotations

import pytest

from protean import BaseEvent, BaseEventHandler, BaseEventSourcedAggregate, handle
from protean.fields import DateTime, Identifier, String


class User(BaseEventSourcedAggregate):
    email = String()
    name = String()
    password_hash = String()


class Email(BaseEventSourcedAggregate):
    email = String()
    sent_at = DateTime()


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class Activated(BaseEvent):
    id = Identifier()
    activated_at = DateTime()


class LoggedIn(BaseEvent):
    id = Identifier()
    activated_at = DateTime()

    class Meta:
        part_of = User


class Subscribed(BaseEvent):
    """An event generated by an external system in its own stream,
    that is consumed and stored as part of the User aggregate.
    """

    id = Identifier()


class Sent(BaseEvent):
    email = String()
    sent_at = DateTime()


class Recalled(BaseEvent):
    email = String()
    sent_at = DateTime()


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def send_activation_email(self, _: Registered) -> None:
        pass

    @handle(Activated)
    def provision_user(self, _: Activated) -> None:
        pass

    @handle(Activated)
    def send_welcome_email(self, _: Activated) -> None:
        pass

    @handle(LoggedIn)
    def record_login(self, _: LoggedIn) -> None:
        pass

    @handle(Subscribed)
    def subscribed_for_notifications(self, _: Subscribed) -> None:
        pass


class EmailEventHandler(BaseEventHandler):
    @handle(Sent)
    def record_sent_email(self, _: Sent) -> None:
        pass

    @handle(Recalled)
    def record_recalls(self, _: Recalled) -> None:
        pass


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User)
    test_domain.register(Registered, stream_name="user")
    test_domain.register(Activated, stream_name="user")
    test_domain.register(LoggedIn, part_of=User)
    test_domain.register(Subscribed, stream_name="subscriptions")
    test_domain.register(Email)
    test_domain.register(Sent, stream_name="email")
    test_domain.register(Recalled, part_of=Email, stream_name="recalls")
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.register(EmailEventHandler, part_of=Email)


def test_automatic_association_of_events_with_aggregate_and_stream():
    assert Registered.meta_.part_of is None
    assert Registered.meta_.stream_name == "user"

    assert Activated.meta_.part_of is None
    assert Activated.meta_.stream_name == "user"

    assert Subscribed.meta_.part_of is None
    assert Subscribed.meta_.stream_name == "subscriptions"

    assert Sent.meta_.part_of is None
    assert Sent.meta_.stream_name == "email"

    assert Recalled.meta_.part_of is Email
    assert Recalled.meta_.stream_name == "recalls"
