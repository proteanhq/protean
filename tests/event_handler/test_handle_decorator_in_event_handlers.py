import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.utils.mixins import handle


class User(BaseAggregate):
    email = String()
    name = String()


class Registered(BaseEvent):
    user_id = Identifier()
    email = String()


class AddressChanged(BaseEvent):
    user_id = Identifier()
    full_address = String()


def test_that_a_handler_is_recorded_against_event_handler(test_domain):
    class UserEventHandlers(BaseEventHandler):
        @handle(Registered)
        def send_email_notification(self, event: Registered) -> None:
            pass

    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(UserEventHandlers, part_of=User)
    test_domain.init(traverse=False)

    assert Registered.__type__ in UserEventHandlers._handlers


def test_that_multiple_handlers_can_be_recorded_against_event_handler(test_domain):
    class UserEventHandlers(BaseEventHandler):
        @handle(Registered)
        def send_email_notification(self, event: Registered) -> None:
            pass

        @handle(AddressChanged)
        def updated_billing_address(self, event: AddressChanged) -> None:
            pass

    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(AddressChanged, part_of=User)
    test_domain.register(UserEventHandlers, part_of=User)
    test_domain.init(traverse=False)

    assert len(UserEventHandlers._handlers) == 2
    assert all(
        handle_name in UserEventHandlers._handlers
        for handle_name in [
            Registered.__type__,
            AddressChanged.__type__,
        ]
    )

    assert len(UserEventHandlers._handlers[Registered.__type__]) == 1
    assert len(UserEventHandlers._handlers[AddressChanged.__type__]) == 1
    assert (
        next(iter(UserEventHandlers._handlers[Registered.__type__]))
        == UserEventHandlers.send_email_notification
    )
    assert (
        next(iter(UserEventHandlers._handlers[AddressChanged.__type__]))
        == UserEventHandlers.updated_billing_address
    )


def test_that_multiple_handlers_can_be_recorded_against_the_same_event(test_domain):
    class UserEventHandlers(BaseEventHandler):
        @handle(Registered)
        def send_email_notification(self, event: Registered) -> None:
            pass

        @handle(Registered)
        def provision_user_accounts(self, event: Registered) -> None:
            pass

    test_domain.register(User)
    test_domain.register(UserEventHandlers, part_of=User)
    test_domain.init(traverse=False)

    assert len(UserEventHandlers._handlers) == 1  # Against Registered Event

    handlers_for_registered = UserEventHandlers._handlers[Registered.__type__]
    assert len(handlers_for_registered) == 2
    assert all(
        handler_method in handlers_for_registered
        for handler_method in [
            UserEventHandlers.send_email_notification,
            UserEventHandlers.provision_user_accounts,
        ]
    )


@pytest.mark.skip(reason="Yet to be implemented")
def test_that_the_handle_method_param_is_an_event(test_domain):
    class UserEventHandlers(BaseEventHandler):
        @handle(Registered)
        def send_email_notification(self, event: str) -> None:
            pass
