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
    test_domain.register(UserLoggedIn)

    with pytest.raises(IncorrectUsageError) as exc:
        identifier = str(uuid4())
        test_domain.raise_(UserLoggedIn(user_id=identifier))

    assert exc.value.messages == {
        "_entity": [
            "Event `UserLoggedIn` needs to be associated with an aggregate or a stream"
        ]
    }


def test_event_definition_with_just_aggregate_cls(test_domain):
    test_domain.register(User)
    test_domain.register(UserLoggedIn, aggregate_cls=User)

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
        pytest.fail("Failed raising event when associated with Aggregate")
