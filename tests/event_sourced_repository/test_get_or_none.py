"""Tests for ``BaseEventSourcedRepository.get_or_none()``.

``get_or_none`` returns ``None`` wherever ``get()`` raises
``ObjectNotFoundError``, and lets every other error propagate.
"""

from datetime import UTC, datetime, timedelta
from unittest import mock
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier, String
from protean.utils.globals import current_domain


class Registered(BaseEvent):
    user_id = Identifier()
    name = String()


class Renamed(BaseEvent):
    user_id = Identifier()
    name = String()


class User(BaseAggregate):
    user_id = Identifier(identifier=True)
    name = String()

    @classmethod
    def register(cls, user_id: str, name: str) -> "User":
        user = cls(user_id=user_id, name=name)
        user.raise_(Registered(user_id=user_id, name=name))
        return user

    def rename(self, name: str) -> None:
        self.raise_(Renamed(user_id=self.user_id, name=name))

    @apply
    def registered(self, event: Registered) -> None:
        self.user_id = event.user_id
        self.name = event.name

    @apply
    def renamed(self, event: Renamed) -> None:
        self.name = event.name


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Renamed, part_of=User)
    test_domain.init(traverse=False)


def _create_user(identifier: str) -> None:
    """Persist a user with two events, so its latest version is 1."""
    repo = current_domain.repository_for(User)
    repo.add(User.register(identifier, "John"))

    user = repo.get(identifier)
    user.rename("Jane")
    repo.add(user)


@pytest.mark.eventstore
def test_returns_none_when_no_stream_exists():
    assert current_domain.repository_for(User).get_or_none("missing") is None


@pytest.mark.eventstore
def test_returns_the_same_aggregate_as_get():
    identifier = str(uuid4())
    _create_user(identifier)
    repo = current_domain.repository_for(User)

    user = repo.get_or_none(identifier)
    expected = repo.get(identifier)

    assert user is not None
    assert user.user_id == expected.user_id == identifier
    assert user.name == expected.name == "Jane"
    assert user._version == expected._version == 1
    assert user._is_temporal is False


@pytest.mark.eventstore
def test_returns_the_identity_mapped_instance_inside_a_unit_of_work():
    identifier = str(uuid4())
    repo = current_domain.repository_for(User)

    with UnitOfWork():
        user = User.register(identifier, "John")
        repo.add(user)

        assert repo.get_or_none(identifier) is user


@pytest.mark.eventstore
def test_returns_none_for_a_version_past_the_end_of_the_stream():
    identifier = str(uuid4())
    _create_user(identifier)

    assert (
        current_domain.repository_for(User).get_or_none(identifier, at_version=6)
        is None
    )


@pytest.mark.eventstore
def test_returns_the_aggregate_at_an_existing_version():
    identifier = str(uuid4())
    _create_user(identifier)

    user = current_domain.repository_for(User).get_or_none(identifier, at_version=0)

    assert user is not None
    assert user._version == 0
    assert user.name == "John"
    assert user._is_temporal is True


@pytest.mark.eventstore
def test_returns_none_for_a_time_before_the_first_event():
    identifier = str(uuid4())
    past = datetime.now(UTC) - timedelta(hours=1)
    _create_user(identifier)

    assert (
        current_domain.repository_for(User).get_or_none(identifier, as_of=past) is None
    )


@pytest.mark.eventstore
def test_returns_the_aggregate_as_of_now():
    identifier = str(uuid4())
    _create_user(identifier)

    user = current_domain.repository_for(User).get_or_none(
        identifier, as_of=datetime.now(UTC) + timedelta(hours=1)
    )

    assert user is not None
    assert user._version == 1
    assert user.name == "Jane"
    assert user._is_temporal is True


@pytest.mark.eventstore
def test_raises_when_both_version_and_time_are_given():
    identifier = str(uuid4())
    _create_user(identifier)

    with pytest.raises(IncorrectUsageError, match="mutually exclusive"):
        current_domain.repository_for(User).get_or_none(
            identifier, at_version=0, as_of=datetime.now(UTC)
        )


@pytest.mark.eventstore
def test_raises_when_event_store_not_configured(test_domain):
    test_domain.event_store._event_store = None

    with pytest.raises(IncorrectUsageError, match="Event store is not configured"):
        current_domain.repository_for(User).get_or_none("missing")


@pytest.mark.eventstore
def test_store_errors_propagate(test_domain):
    with mock.patch.object(
        test_domain.event_store.store,
        "load_aggregate",
        side_effect=RuntimeError("store is down"),
    ):
        with pytest.raises(RuntimeError, match="store is down"):
            current_domain.repository_for(User).get_or_none("missing")
