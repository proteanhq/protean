import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.fields import Identifier, String
from protean.utils import fully_qualified_name


class User(BaseAggregate):
    email: String()
    name: String()


class Register(BaseCommand):
    user_id: Identifier()
    email: String()


def test_registering_an_command_handler_manually(test_domain):
    class UserCommandHandler(BaseCommandHandler):
        pass

    try:
        test_domain.register(UserCommandHandler, part_of=User)
    except Exception:
        pytest.fail("Failed to register an Command Handler manually")

    assert (
        fully_qualified_name(UserCommandHandler)
        in test_domain.registry.command_handlers
    )


def test_registering_an_command_handler_via_annotation(test_domain):
    try:

        @test_domain.command_handler(part_of=User)
        class UserCommandHandler(BaseCommandHandler):
            pass

    except Exception:
        pytest.fail("Failed to register an Command Handler via annotation")

    assert (
        fully_qualified_name(UserCommandHandler)
        in test_domain.registry.command_handlers
    )
