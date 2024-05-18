from protean import BaseAggregate, BaseCommand, BaseCommandHandler
from protean.fields import Identifier, String


class User(BaseAggregate):
    email = String()
    name = String()


class Register(BaseCommand):
    user_id = Identifier()
    email = String()


def test_aggregate_cls_specified_during_registration(test_domain):
    class UserCommandHandlers(BaseCommandHandler):
        pass

    test_domain.register(UserCommandHandlers, part_of=User)
    assert UserCommandHandlers.meta_.part_of == User


def test_aggregate_cls_specified_as_a_meta_attribute(test_domain):
    class UserCommandHandlers(BaseCommandHandler):
        class Meta:
            part_of = User

    test_domain.register(UserCommandHandlers)
    assert UserCommandHandlers.meta_.part_of == User


def test_aggregate_cls_defined_via_annotation(
    test_domain,
):
    @test_domain.command_handler(part_of=User)
    class UserCommandHandlers(BaseCommandHandler):
        pass

    assert UserCommandHandlers.meta_.part_of == User
