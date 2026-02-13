import mock
import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import _LegacyBaseCommand as BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.fields import Identifier, String
from protean.utils.mixins import handle


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


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Register, part_of=User)
    test_domain.register(UserCommandHandlers, part_of=User)
    test_domain.init(traverse=False)


# This only works because of the `__init__.py` file in tests/command_handler folder
#   because it needs to import `dummy` method from `tests.command_handler.test_uow_around_command_handlers`
@mock.patch("protean.utils.mixins.UnitOfWork.__enter__")
@mock.patch("tests.command_handler.test_uow_around_command_handlers.dummy")
@mock.patch("protean.utils.mixins.UnitOfWork.__exit__")
def test_that_method_is_enclosed_in_uow(mock_exit, mock_dummy, mock_enter):
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
