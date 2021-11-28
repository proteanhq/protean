import pytest

from protean import BaseAggregate, BaseEvent, BaseEventHandler
from protean.fields import Identifier, String
from protean.utils import fully_qualified_name


class User(BaseAggregate):
    email = String()
    name = String()


class Registered(BaseEvent):
    user_id = Identifier()
    email = String()


def test_registering_an_event_handler_manually(test_domain):
    class UserEventHandlers(BaseEventHandler):
        pass

    try:
        test_domain.register(UserEventHandlers, aggregate_cls=User)
    except Exception:
        pytest.fail("Failed to register an Event Handler manually")

    assert (
        fully_qualified_name(UserEventHandlers) in test_domain.registry.event_handlers
    )


def test_registering_an_event_handler_via_annotation(test_domain):
    try:

        @test_domain.event_handler(aggregate_cls=User)
        class UserEventHandlers(BaseEventHandler):
            pass

    except Exception:
        pytest.fail("Failed to register an Event Handler via annotation")

    assert (
        fully_qualified_name(UserEventHandlers) in test_domain.registry.event_handlers
    )
