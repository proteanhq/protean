from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventSourcedAggregate
from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier, String


class UserRegistered(BaseEvent):
    id = Identifier(required=True)
    name = String(max_length=50, required=True)
    email = String(required=True)


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)
    email = String()
    name = String()

    @classmethod
    def register(cls, id, name, email):
        user = cls(id=id, name=name, email=email)
        user.raise_(UserRegistered(id=id, name=name, email=email))
        return user


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.init(traverse=False)


def test_exception_on_empty_aggregate_object(test_domain):
    with pytest.raises(IncorrectUsageError) as exception:
        test_domain.repository_for(User).add(None)

    assert exception.value.messages == {
        "_entity": ["Aggregate object to persist is invalid"]
    }


def test_successful_persistence_of_aggregate(test_domain):
    user = User.register(id=str(uuid4()), name="John Doe", email="john.doe@example.com")
    assert len(user._events) == 1

    test_domain.repository_for(User).add(user)
    assert len(user._events) == 0

    event_messages = test_domain.event_store.store.read(f"user-{user.id}")
    assert len(event_messages) == 1


def test_aggregate_with_no_changes_is_not_acted_on(test_domain):
    user = User(id=str(uuid4()), name="John Doe", email="john.doe@example.com")
    assert len(user._events) == 0

    test_domain.repository_for(User).add(user)
    event_messages = test_domain.event_store.store.read(f"user-{user.id}")
    assert len(event_messages) == 0
