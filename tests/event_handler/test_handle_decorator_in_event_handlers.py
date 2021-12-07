from protean import BaseAggregate, BaseEvent, BaseEventHandler, handle
from protean.fields import Identifier, String
from protean.utils import fully_qualified_name


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
    test_domain.register(UserEventHandlers, aggregate_cls=User)

    assert fully_qualified_name(Registered) in UserEventHandlers._handlers


def test_that_multiple_handlers_can_be_recorded_against_event_handler(test_domain):
    class UserEventHandlers(BaseEventHandler):
        @handle(Registered)
        def send_email_notification(self, event: Registered) -> None:
            pass

        @handle(AddressChanged)
        def updated_billing_address(self, event: AddressChanged) -> None:
            pass

    test_domain.register(User)
    test_domain.register(UserEventHandlers, aggregate_cls=User)

    assert len(UserEventHandlers._handlers) == 2
    assert all(
        handle_name in UserEventHandlers._handlers
        for handle_name in [
            fully_qualified_name(Registered),
            fully_qualified_name(AddressChanged),
        ]
    )

    assert len(UserEventHandlers._handlers[fully_qualified_name(Registered)]) == 1
    assert len(UserEventHandlers._handlers[fully_qualified_name(AddressChanged)]) == 1
    assert (
        next(iter(UserEventHandlers._handlers[fully_qualified_name(Registered)]))
        == UserEventHandlers.send_email_notification
    )
    assert (
        next(iter(UserEventHandlers._handlers[fully_qualified_name(AddressChanged)]))
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
    test_domain.register(UserEventHandlers, aggregate_cls=User)

    assert len(UserEventHandlers._handlers) == 1  # Against Registered Event

    handlers_for_registered = UserEventHandlers._handlers[
        fully_qualified_name(Registered)
    ]
    assert len(handlers_for_registered) == 2
    assert all(
        handler_method in handlers_for_registered
        for handler_method in [
            UserEventHandlers.send_email_notification,
            UserEventHandlers.provision_user_accounts,
        ]
    )
