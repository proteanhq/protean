from __future__ import annotations

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent


class User(BaseAggregate):
    email: str | None = None
    name: str | None = None

    @classmethod
    def register(cls, id, email, name):
        user = User(id=id, email=email, name=name)
        user.raise_(Registered(id=id, email=email, name=name))

        return user

    def activate(self):
        self.raise_(Activated(id=self.id))

    def rename(self, name):
        self.name = name
        self.raise_(Renamed(id=self.id, name=name))


class Registered(BaseEvent):
    id: str | None = None
    email: str | None = None
    name: str | None = None


class Activated(BaseEvent):
    id: str


class Renamed(BaseEvent):
    id: str
    name: str


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Activated, part_of=User)
    test_domain.register(Renamed, part_of=User)
    test_domain.init(traverse=False)


@pytest.fixture
def registered_user(test_domain):
    identifier = str(uuid4())

    user = User.register(id=identifier, email="john.doe@example.com", name="John Doe")
    test_domain.event_store.store.append(user._events[0])

    return user


@pytest.mark.eventstore
def test_reading_events_of_type_with_just_one_message(test_domain, registered_user):
    events = test_domain.event_store.store._events_of_type(Registered)
    assert len(events) == 1
    assert isinstance(events[0], Registered)


@pytest.mark.eventstore
def test_reading_events_of_type_with_other_events_present(test_domain, registered_user):
    registered_user.activate()
    test_domain.event_store.store.append(registered_user._events[1])

    assert isinstance(
        test_domain.event_store.store._events_of_type(Registered)[0], Registered
    )
    assert isinstance(
        test_domain.event_store.store._events_of_type(Activated)[0], Activated
    )


class TestEventStoreEventsOfType:
    @pytest.fixture(autouse=True)
    def activate_and_rename(self, registered_user, test_domain):
        registered_user.activate()
        test_domain.event_store.store.append(registered_user._events[1])

        for i in range(10):
            registered_user.rename(name=f"John Doe {i}")
            test_domain.event_store.store.append(registered_user._events[-1])

        yield

    @pytest.mark.eventstore
    def test_reading_events_of_type_with_multiple_events(self, test_domain):
        events = test_domain.event_store.store._events_of_type(Renamed)
        assert len(events) == 10
        assert events[-1].name == "John Doe 9"

    @pytest.mark.eventstore
    def test_reading_events_of_type_with_multiple_events_in_stream(self, test_domain):
        events = test_domain.event_store.store._events_of_type(Renamed, "test::user")
        assert len(events) == 10
        assert events[-1].name == "John Doe 9"

    @pytest.mark.eventstore
    def test_reading_events_of_type_with_multiple_events_in_different_stream(
        self, test_domain
    ):
        events = test_domain.event_store.store._events_of_type(Renamed, "test::group")
        assert len(events) == 0
