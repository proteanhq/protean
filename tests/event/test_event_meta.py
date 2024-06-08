from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventSourcedAggregate
from protean.exceptions import IncorrectUsageError
from protean.fields import String
from protean.fields.basic import Identifier


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)
    email = String()
    name = String()


class UserLoggedIn(BaseEvent):
    user_id = Identifier(identifier=True)


def test_event_definition_without_aggregate_or_stream(test_domain):
    test_domain.register(User)

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.register(UserLoggedIn)

    assert exc.value.messages == {
        "_event": [
            "Event `UserLoggedIn` needs to be associated with an aggregate or a stream"
        ]
    }


def test_event_definition_with_just_aggregate_cls(test_domain):
    test_domain.register(User)
    test_domain.register(UserLoggedIn, part_of=User)
    test_domain.init(traverse=False)

    try:
        identifier = str(uuid4())
        test_domain.raise_(UserLoggedIn(user_id=identifier))
    except IncorrectUsageError:
        pytest.fail("Failed raising event when associated with Aggregate")


def test_event_definition_with_just_stream(test_domain):
    test_domain.register(User)
    test_domain.register(UserLoggedIn, stream_name="user")

    try:
        identifier = str(uuid4())
        test_domain.raise_(UserLoggedIn(user_id=identifier))
    except IncorrectUsageError:
        pytest.fail("Failed raising event when associated with Stream")


def test_that_abstract_events_can_be_defined_without_aggregate_or_stream(test_domain):
    class AbstractEvent(BaseEvent):
        foo = String()

    try:
        test_domain.register(AbstractEvent, abstract=True)
    except Exception:
        pytest.fail(
            "Abstract events should be definable without being associated with an aggregate or a stream"
        )


def test_that_aggregate_cls_is_resolved_correctly(test_domain):
    test_domain.register(User)
    test_domain.register(UserLoggedIn, part_of="User")

    test_domain.init(traverse=False)
    assert UserLoggedIn.meta_.part_of == User
