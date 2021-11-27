from protean import BaseEvent, BaseEventHandler
from protean.fields import Identifier, String


class Registered(BaseEvent):
    user_id = Identifier()
    email = String()


def test_event_option_specified_during_registration(test_domain):
    class SendInviteEmail(BaseEventHandler):
        def __call__(self, event: Registered) -> None:
            pass

    test_domain.register(SendInviteEmail, event=Registered)
    assert SendInviteEmail.meta_.event == Registered


def test_event_option_specified_as_a_meta_attribute(test_domain):
    class SendInviteEmail(BaseEventHandler):
        def __call__(self, event: Registered) -> None:
            pass

        class Meta:
            event = Registered

    test_domain.register(SendInviteEmail)
    assert SendInviteEmail.meta_.event == Registered


def test_stream_name_option_defined_via_annotation(test_domain,):
    @test_domain.event_handler(event=Registered)
    class SendInviteEmail(BaseEventHandler):
        def __call__(self, event: Registered) -> None:
            pass

    assert SendInviteEmail.meta_.event == Registered
