from enum import Enum
from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventSourcedAggregate, UnitOfWork, apply
from protean.fields import Identifier, String
from protean.port.event_store import BaseEventStore


class UserStatus(Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ARCHIVED = "ARCHIVED"


class UserRegistered(BaseEvent):
    user_id = Identifier(required=True)
    name = String(max_length=50, required=True)
    email = String(required=True)


class UserActivated(BaseEvent):
    user_id = Identifier(required=True)


class UserRenamed(BaseEvent):
    user_id = Identifier(required=True)
    name = String(required=True, max_length=50)


class User(BaseEventSourcedAggregate):
    user_id = Identifier(identifier=True)
    name = String(max_length=50, required=True)
    email = String(required=True)
    status = String(choices=UserStatus)

    @classmethod
    def register(cls, user_id, name, email):
        user = cls(user_id=user_id, name=name, email=email)
        user.raise_(UserRegistered(user_id=user_id, name=name, email=email))
        return user

    def activate(self):
        self.raise_(UserActivated(user_id=self.user_id))

    def change_name(self, name):
        self.raise_(UserRenamed(user_id=self.user_id, name=name))

    @apply(UserRegistered)
    def registered(self, event: UserRegistered):
        self.status = UserStatus.INACTIVE.value

    @apply(UserActivated)
    def activated(self, event: UserActivated):
        self.status = UserStatus.ACTIVE.value

    @apply(UserRenamed)
    def renamed(self, event: UserRenamed):
        self.name = event.name


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)


@pytest.mark.eventstore
def test_that_a_new_stream_has_no_snapshot(test_domain):
    identifier = str(uuid4())
    repo = test_domain.repository_for(User)

    with UnitOfWork():
        user = User.register(
            user_id=identifier, name="John Doe", email="john.doe@example.com"
        )
        user.activate()
        repo.add(user)

    snapshot = test_domain.event_store.store._read_last_message(
        f"user:snapshot-{identifier}"
    )
    assert snapshot is None


@pytest.mark.eventstore
def test_that_snapshot_is_constructed_after_threshold(test_domain):
    identifier = str(uuid4())
    repo = test_domain.repository_for(User)

    with UnitOfWork():
        user = User.register(
            user_id=identifier, name="John Doe", email="john.doe@example.com"
        )
        user.activate()
        repo.add(user)

    for i in range(
        3, BaseEventStore.SNAPSHOT_THRESHOLD + 2
    ):  # Start at 3 because we already have two events
        with UnitOfWork():
            user = repo.get(identifier)
            user.change_name(f"John Doe {i}")
            repo.add(user)

    snapshot = test_domain.event_store.store._read_last_message(
        f"user:snapshot-{identifier}"
    )
    assert snapshot is not None
    assert User(**snapshot["data"]) == user
    assert snapshot["data"]["name"] == "John Doe 10"


@pytest.mark.eventstore
def test_that_a_stream_can_have_multiple_snapshots_but_latest_is_considered(
    test_domain,
):
    identifier = str(uuid4())
    repo = test_domain.repository_for(User)

    with UnitOfWork():
        user = User.register(
            user_id=identifier, name="John Doe", email="john.doe@example.com"
        )
        user.activate()
        repo.add(user)

    for i in range(3, (2 * BaseEventStore.SNAPSHOT_THRESHOLD) + 2):
        with UnitOfWork():
            user = repo.get(identifier)
            user.change_name(f"John Doe {i}")
            repo.add(user)

    snapshot = test_domain.event_store.store._read_last_message(
        f"user:snapshot-{identifier}"
    )
    assert snapshot is not None
    assert User(**snapshot["data"]) == user
    assert snapshot["data"]["name"] == "John Doe 20"


@pytest.mark.eventstore
def test_that_a_stream_with_a_snapshop_and_no_further_events_is_reconstructed_correctly(
    test_domain,
):
    identifier = str(uuid4())
    repo = test_domain.repository_for(User)

    with UnitOfWork():
        user = User.register(
            user_id=identifier, name="John Doe", email="john.doe@example.com"
        )
        user.activate()
        repo.add(user)

    for i in range(3, (2 * BaseEventStore.SNAPSHOT_THRESHOLD) + 2):
        with UnitOfWork():
            user = repo.get(identifier)
            user.change_name(f"John Doe {i}")
            repo.add(user)

    snapshot = test_domain.event_store.store._read_last_message(
        f"user:snapshot-{identifier}"
    )
    assert snapshot is not None
    assert User(**snapshot["data"]) == user
    assert snapshot["data"]["name"] == "John Doe 20"


@pytest.mark.skip(reason="Yet to implement")
@pytest.mark.eventstore
def test_that_snapshots_preserve_performance_even_with_large_no_of_events(test_domain):
    # Measure the time taken to load aggregate with 10 events
    # Add 1000 events to Aggregate
    # Measure the time taken to load aggregate with 1000 events
    pass
