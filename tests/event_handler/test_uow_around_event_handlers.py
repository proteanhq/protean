import mock

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.utils.mixins import handle


class User(BaseAggregate):
    email: String()
    name: String()


class Registered(BaseEvent):
    user_id: Identifier()
    email: String()


def dummy(*args):
    pass


class UserEventHandlers(BaseEventHandler):
    @handle(Registered)
    def send_email_notification(self, event: Registered) -> None:
        dummy(self, event)


@mock.patch("protean.utils.mixins.UnitOfWork.__enter__")
@mock.patch("tests.event_handler.test_uow_around_event_handlers.dummy")
@mock.patch("protean.utils.mixins.UnitOfWork.__exit__")
def test_that_method_is_enclosed_in_uow(mock_exit, mock_dummy, mock_enter, test_domain):
    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.init(traverse=False)

    mock_parent = mock.Mock()

    mock_parent.attach_mock(mock_enter, "m1")
    mock_parent.attach_mock(mock_dummy, "m2")
    mock_parent.attach_mock(mock_exit, "m3")

    handler_obj = UserEventHandlers()
    event = Registered(user_id=1, email="foo@bar.com")

    # Call the handler
    handler_obj.send_email_notification(event)

    mock_parent.assert_has_calls(
        [
            mock.call.m1(),
            mock.call.m2(handler_obj, event),
            mock.call.m3(None, None, None),
        ]
    )
