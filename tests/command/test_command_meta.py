from uuid import uuid4

import pytest

from protean import BaseAggregate, BaseCommand
from protean.exceptions import IncorrectUsageError
from protean.fields import String
from protean.fields.basic import Identifier


class User(BaseAggregate):
    id = Identifier(identifier=True)
    email = String()
    name = String()


class Register(BaseCommand):
    user_id = Identifier(identifier=True)
    email = String()
    name = String()


def test_command_definition_without_aggregate_or_stream(test_domain):
    test_domain.register(User, is_event_sourced=True)

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.register(Register)

    assert exc.value.messages == {
        "_command": [
            "Command `Register` needs to be associated with an aggregate or a stream"
        ]
    }


def test_that_abstract_commands_can_be_defined_without_aggregate_or_stream(test_domain):
    class AbstractCommand(BaseCommand):
        foo = String()

    try:
        test_domain.register(AbstractCommand, abstract=True)
    except Exception:
        pytest.fail(
            "Abstract commands should be definable without being associated with an aggregate or a stream"
        )


@pytest.mark.eventstore
def test_command_associated_with_aggregate(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.init(traverse=False)

    identifier = str(uuid4())
    test_domain.process(
        Register(
            user_id=identifier,
            email="john.doe@gmail.com",
            name="John Doe",
        )
    )

    messages = test_domain.event_store.store.read("test::user:command")

    assert len(messages) == 1
    messages[0].stream_name == f"test::user:command-{identifier}"


@pytest.mark.eventstore
def test_command_associated_with_aggregate_with_custom_stream_name(test_domain):
    test_domain.register(User, is_event_sourced=True, stream_category="foo")
    test_domain.register(Register, part_of=User)
    test_domain.init(traverse=False)

    identifier = str(uuid4())
    test_domain.process(
        Register(
            user_id=identifier,
            email="john.doe@gmail.com",
            name="John Doe",
        )
    )

    messages = test_domain.event_store.store.read("test::foo:command")

    assert len(messages) == 1
    messages[0].stream_name == f"test::foo:command-{identifier}"


def test_aggregate_cluster_of_event(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.init(traverse=False)

    assert Register.meta_.aggregate_cluster == User
