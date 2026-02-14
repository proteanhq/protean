import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier, String


class User(BaseAggregate):
    email = String()
    name = String()


class Register(BaseCommand):
    user_id = Identifier()
    email = String()


def test_part_of_is_mandatory(test_domain):
    class UserCommandHandlers(BaseCommandHandler):
        pass

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.register(UserCommandHandlers)

    assert (
        exc.value.args[0]
        == "Command Handler `UserCommandHandlers` needs to be associated with an Aggregate"
    )


def test_part_of_specified_as_a_meta_attribute(test_domain):
    class UserCommandHandlers(BaseCommandHandler):
        pass

    test_domain.register(UserCommandHandlers, part_of=User)
    assert UserCommandHandlers.meta_.part_of == User


def test_part_of_defined_via_annotation(
    test_domain,
):
    @test_domain.command_handler(part_of=User)
    class UserCommandHandlers(BaseCommandHandler):
        pass

    assert UserCommandHandlers.meta_.part_of == User


class TestCommandHandlerStreamCategoryDerivation:
    """Tests for stream_category derivation from aggregate."""

    def test_stream_category_derived_from_aggregate(self, test_domain):
        """Command handler stream_category is always derived from aggregate."""
        test_domain.register(User)

        @test_domain.command_handler(part_of=User)
        class UserCommandHandler(BaseCommandHandler):
            pass

        assert UserCommandHandler.meta_.stream_category == "test::user:command"

    def test_stream_category_derived_without_explicit_aggregate_registration(
        self, test_domain
    ):
        """Command handler stream_category derived even without explicit aggregate registration."""

        @test_domain.command_handler(part_of=User)
        class UserCommandHandler(BaseCommandHandler):
            pass

        # stream_category should be derived from Order's meta
        assert (
            UserCommandHandler.meta_.stream_category
            == f"{User.meta_.stream_category}:command"
        )
