import pytest

from protean import BaseEvent, BaseEventHandler
from protean.fields import Identifier, String
from protean.utils import fully_qualified_name


class Registered(BaseEvent):
    user_id = Identifier()
    email = String()


def test_registering_an_event_handler_manually(test_domain):
    class SendInviteEmail(BaseEventHandler):
        def __call__(self, event: Registered) -> None:
            pass

    try:
        test_domain.register(SendInviteEmail, event=Registered)
    except Exception:
        pytest.fail("Failed to register an Event Handler manually")

    assert fully_qualified_name(SendInviteEmail) in test_domain.registry.event_handlers


def test_registering_an_event_handler_via_annotation(test_domain):
    try:

        @test_domain.event_handler(event=Registered)
        class SendInviteEmail(BaseEventHandler):
            def __call__(self, event: Registered) -> None:
                pass

    except Exception:
        pytest.fail("Failed to register an Event Handler via annotation")

    assert fully_qualified_name(SendInviteEmail) in test_domain.registry.event_handlers
