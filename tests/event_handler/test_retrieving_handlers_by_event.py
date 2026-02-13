from __future__ import annotations

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import _LegacyBaseEvent as BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import DateTime, Identifier, String
from protean.utils.mixins import handle


class User(BaseAggregate):
    email = String()
    name = String()
    password_hash = String()


class Email(BaseAggregate):
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


class Renamed(BaseEvent):
    id = Identifier()
    name = String()


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


class UserMetrics(BaseEventHandler):
    @handle(Registered)
    def count_registrations(self, _: BaseEvent) -> None:
        pass


class AllEventsHandler(BaseEventHandler):
    @handle("$any")
    def universal_handler(self, _: BaseEvent) -> None:
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Activated, part_of=User)
    test_domain.register(Renamed, part_of=User)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.register(UserMetrics, part_of=User)
    test_domain.register(Email, is_event_sourced=True)
    test_domain.register(Sent, part_of=Email)
    test_domain.register(EmailEventHandler, part_of=Email)


def test_retrieving_handler_by_event(test_domain):
    test_domain.init(traverse=False)
    assert test_domain.handlers_for(Registered()) == {UserEventHandler, UserMetrics}
    assert test_domain.handlers_for(Sent()) == {EmailEventHandler}


def test_that_all_streams_handler_is_returned(test_domain):
    test_domain.register(AllEventsHandler, stream_category="$all")
    test_domain.init(traverse=False)
    assert test_domain.handlers_for(Renamed()) == {AllEventsHandler}


def test_that_all_streams_handler_is_always_returned_with_other_handlers(test_domain):
    test_domain.register(AllEventsHandler, stream_category="$all")
    test_domain.init(traverse=False)

    assert test_domain.handlers_for(Registered()) == {
        UserEventHandler,
        UserMetrics,
        AllEventsHandler,
    }
    assert test_domain.handlers_for(Sent()) == {EmailEventHandler, AllEventsHandler}
