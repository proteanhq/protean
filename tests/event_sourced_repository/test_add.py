from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError


class UserRegistered(BaseEvent):
    id: str
    name: str
    email: str


class User(BaseAggregate):
    email: str | None = None
    name: str | None = None

    @classmethod
    def register(cls, id, name, email):
        user = cls(id=id, name=name, email=email)
        user.raise_(UserRegistered(id=id, name=name, email=email))
        return user


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.init(traverse=False)


def test_exception_on_empty_aggregate_object(test_domain):
    with pytest.raises(IncorrectUsageError) as exception:
        test_domain.repository_for(User).add(None)

    assert exception.value.args[0] == "Aggregate object to persist is invalid"


def test_successful_persistence_of_aggregate(test_domain):
    user = User.register(id=str(uuid4()), name="John Doe", email="john.doe@example.com")
    assert len(user._events) == 1

    test_domain.repository_for(User).add(user)
    assert len(user._events) == 0

    event_messages = test_domain.event_store.store.read(f"test::user-{user.id}")
    assert len(event_messages) == 1


def test_aggregate_with_no_changes_is_not_acted_on(test_domain):
    user = User(id=str(uuid4()), name="John Doe", email="john.doe@example.com")
    assert len(user._events) == 0

    test_domain.repository_for(User).add(user)
    event_messages = test_domain.event_store.store.read(f"test::user-{user.id}")
    assert len(event_messages) == 0
