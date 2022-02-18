from uuid import uuid4

import pytest

from protean import BaseCommand, BaseEventSourcedAggregate
from protean.exceptions import IncorrectUsageError
from protean.fields import String
from protean.fields.basic import Identifier


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)
    email = String()
    name = String()


class Register(BaseCommand):
    user_id = Identifier(identifier=True)
    email = String()
    name = String()


def test_command_definition_without_aggregate_or_stream(test_domain):
    test_domain.register(User)
    test_domain.register(Register)

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.process(
            Register(
                user_id=str(uuid4()),
                email="john.doe@gmail.com",
                name="John Doe",
            )
        )
    assert exc.value.messages == {
        "_entity": [
            "Command `Register` needs to be associated with an aggregate or a stream"
        ]
    }


def test_that_abstract_commands_can_be_defined_without_aggregate_or_stream(test_domain):
    class AbstractCommand(BaseCommand):
        foo = String()

        class Meta:
            abstract = True

    try:
        test_domain.register(AbstractCommand)
    except Exception:
        pytest.fail(
            "Abstract commands should be definable without being associated with an aggregate or a stream"
        )


@pytest.mark.eventstore
def test_command_associated_with_aggregate(test_domain):
    test_domain.register(User)
    test_domain.register(Register, aggregate_cls=User)

    identifier = str(uuid4())
    test_domain.process(
        Register(
            user_id=identifier,
            email="john.doe@gmail.com",
            name="John Doe",
        )
    )

    messages = test_domain.event_store.store.read("user:command")

    assert len(messages) == 1
    messages[0].stream_name == f"user:command-{identifier}"


@pytest.mark.eventstore
def test_command_associated_with_stream_name(test_domain):
    test_domain.register(Register, stream_name="foo")

    identifier = str(uuid4())
    test_domain.process(
        Register(
            user_id=identifier,
            email="john.doe@gmail.com",
            name="John Doe",
        )
    )

    messages = test_domain.event_store.store.read("foo:command")

    assert len(messages) == 1
    messages[0].stream_name == f"foo:command-{identifier}"
