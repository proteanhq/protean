from __future__ import annotations

from datetime import datetime

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.utils.mixins import handle


class User(BaseAggregate):
    email: str | None = None
    name: str | None = None
    password_hash: str | None = None


class Email(BaseAggregate):
    email: str | None = None
    sent_at: datetime | None = None


class Registered(BaseEvent):
    id: str | None = None
    email: str | None = None
    name: str | None = None
    password_hash: str | None = None


class Activated(BaseEvent):
    id: str | None = None
    activated_at: datetime | None = None


class Sent(BaseEvent):
    email: str | None = None
    sent_at: datetime | None = None


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
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Activated, part_of=User)
    test_domain.register(Email, is_event_sourced=True)
    test_domain.register(Sent, part_of=Email)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.register(EmailEventHandler, part_of=Email)
    test_domain.init(traverse=False)


def test_streams_initialization(test_domain):
    assert len(test_domain.event_store._event_streams) == 2
    assert all(
        stream_category in test_domain.event_store._event_streams
        for stream_category in ["test::user", "test::email"]
    )

    assert test_domain.event_store._event_streams["test::user"] == {UserEventHandler}
    assert test_domain.event_store._event_streams["test::email"] == {EmailEventHandler}
