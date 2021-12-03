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

    test_domain.register(UserCommandHandlers, aggregate_cls=User)
    assert UserCommandHandlers.meta_.aggregate_cls == User


def test_aggregate_cls_specified_as_a_meta_attribute(test_domain):
    class UserCommandHandlers(BaseCommandHandler):
        class Meta:
            aggregate_cls = User

    test_domain.register(UserCommandHandlers)
    assert UserCommandHandlers.meta_.aggregate_cls == User


def test_aggregate_cls_defined_via_annotation(
    test_domain,
):
    @test_domain.command_handler(aggregate_cls=User)
    class UserCommandHandlers(BaseCommandHandler):
        pass

    assert UserCommandHandlers.meta_.aggregate_cls == User
