from __future__ import annotations

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

    class Meta:
        part_of = User


class AllEventsHandler(BaseEventHandler):
    @handle("$any")
    def universal_handler(self, _: BaseEvent) -> None:
        pass


def test_retrieving_handler_by_event(test_domain):
    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Activated, part_of=User)
    test_domain.register(Renamed, part_of=User)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.register(UserMetrics, part_of=User)
    test_domain.register(Email)
    test_domain.register(Sent, part_of=Email)
    test_domain.register(EmailEventHandler, part_of=Email)

    assert test_domain.handlers_for(Registered()) == {UserEventHandler, UserMetrics}
    assert test_domain.handlers_for(Sent()) == {EmailEventHandler}


def test_that_all_streams_handler_is_returned(test_domain):
    test_domain.register(AllEventsHandler, stream_name="$all")
    assert test_domain.handlers_for(Renamed()) == {AllEventsHandler}


def test_that_all_streams_handler_is_always_returned_with_other_handlers(test_domain):
    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Activated, part_of=User)
    test_domain.register(Renamed, part_of=User)
    test_domain.register(AllEventsHandler, stream_name="$all")
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.register(UserMetrics, part_of=User)
    test_domain.register(Email)
    test_domain.register(Sent, part_of=Email)
    test_domain.register(EmailEventHandler, part_of=Email)

    assert test_domain.handlers_for(Registered()) == {
        UserEventHandler,
        UserMetrics,
        AllEventsHandler,
    }
    assert test_domain.handlers_for(Sent()) == {EmailEventHandler, AllEventsHandler}
