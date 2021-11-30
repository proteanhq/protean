import mock

from protean import BaseAggregate, BaseCommand, BaseCommandHandler, handle
from protean.fields import Identifier, String


class User(BaseAggregate):
    email = String()
    name = String()


class Register(BaseCommand):
    user_id = Identifier()
    email = String()


def dummy(*args):
    pass


class UserCommandHandlers(BaseCommandHandler):
    @handle(Register)
    def register(self, command: Register) -> None:
        dummy(self, command)


@mock.patch("protean.utils.mixins.UnitOfWork.__enter__")
@mock.patch("tests.command_handler.test_uow_around_command_handlers.dummy")
@mock.patch("protean.utils.mixins.UnitOfWork.__exit__")
def test_that_method_is_enclosed_in_uow(mock_exit, mock_dummy, mock_enter, test_domain):
    mock_parent = mock.Mock()

    mock_parent.attach_mock(mock_enter, "m1")
    mock_parent.attach_mock(mock_dummy, "m2")
    mock_parent.attach_mock(mock_exit, "m3")

    handler_obj = UserCommandHandlers()
    command = Register(user_id=1, email="foo@bar.com")

    # Call the handler
    handler_obj.register(command)

    mock_parent.assert_has_calls(
        [
            mock.call.m1(),
            mock.call.m2(handler_obj, command),
            mock.call.m3(None, None, None),
        ]
    )
