from __future__ import annotations

import pytest

from protean import BaseEvent, BaseEventHandler, BaseEventSourcedAggregate, handle
from protean.fields import DateTime, Identifier, String


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
    email = String()
    name = String()
    password_hash = String()


class Email(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
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


class Sent(BaseEvent):
    email = String()
    sent_at = DateTime()


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def send_activation_email(self, event: Registered) -> None:
        pass

    @handle(Activated)
    def provision_user(self, event: Activated) -> None:
        pass

    @handle(Activated)
    def send_welcome_email(self, event: Activated) -> None:
        pass


class EmailEventHandler(BaseEventHandler):
    @handle(Sent)
    def record_sent_email(self, event: Sent) -> None:
        pass


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User)
    test_domain.register(Email)
    test_domain.register(UserEventHandler, aggregate_cls=User)
    test_domain.register(EmailEventHandler, aggregate_cls=Email)


def test_streams_initialization(test_domain):
    test_domain.event_store.store  # Initializes store if not initialized already

    assert len(test_domain.event_store._event_streams) == 2
    assert all(
        stream_name in test_domain.event_store._event_streams
        for stream_name in ["user", "email"]
    )

    assert test_domain.event_store._event_streams["user"] == {UserEventHandler}
    assert test_domain.event_store._event_streams["email"] == {EmailEventHandler}
