from __future__ import annotations

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


class UserMetrics(BaseEventHandler):
    @handle(Registered)
    def count_registrations(self, _: BaseEventHandler) -> None:
        pass

    class Meta:
        aggregate_cls = User


def test_retrieving_handler_by_event(test_domain):
    test_domain.register(UserEventHandler, aggregate_cls=User)
    test_domain.register(UserMetrics, aggregate_cls=User)
    test_domain.register(EmailEventHandler, aggregate_cls=Email)

    assert test_domain.handlers_for(Registered()) == {UserEventHandler, UserMetrics}
    assert test_domain.handlers_for(Sent()) == {EmailEventHandler}
