from __future__ import annotations

from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventSourcedAggregate
from protean.fields import String
from protean.fields.basic import Identifier


class User(BaseEventSourcedAggregate):
    email = String()
    name = String(max_length=50)

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
    id = Identifier()
    email = String()
    name = String()


class Activated(BaseEvent):
    id = Identifier(required=True)


class Renamed(BaseEvent):
    id = Identifier(required=True)
    name = String(required=True, max_length=50)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Activated, part_of=User)
    test_domain.register(Renamed, part_of=User)
    test_domain.init(traverse=False)


@pytest.fixture(autouse=True)
def registered_user(test_domain):
    identifier = str(uuid4())

    user = User.register(id=identifier, email="john.doe@example.com", name="John Doe")
    test_domain.event_store.store.append_aggregate_event(user, user._events[0])

    return user


@pytest.mark.eventstore
def test_reading_the_last_event_of_type_with_just_one_message(test_domain):
    event = test_domain.event_store.last_event_of_type(Registered)
    assert event is not None


@pytest.mark.eventstore
def test_reading_the_last_event_of_type_with_other_events_present(
    test_domain, registered_user
):
    registered_user.activate()
    test_domain.event_store.store.append_aggregate_event(
        registered_user, registered_user._events[1]
    )

    assert isinstance(
        test_domain.event_store.last_event_of_type(Registered), Registered
    )
    assert isinstance(test_domain.event_store.last_event_of_type(Activated), Activated)


class TestEventStoreEventsOfType:
    @pytest.fixture(autouse=True)
    def activate_and_rename(self, registered_user, test_domain):
        registered_user.activate()
        test_domain.event_store.store.append_aggregate_event(
            registered_user, registered_user._events[1]
        )

        for i in range(10):
            registered_user.rename(name=f"John Doe {i}")
            test_domain.event_store.store.append_aggregate_event(
                registered_user, registered_user._events[-1]
            )

        yield

    @pytest.mark.eventstore
    def test_reading_the_last_event_of_type_with_multiple_events(
        self, test_domain, registered_user
    ):
        for i in range(10):
            registered_user.rename(name=f"John Doe {i}")
            test_domain.event_store.store.append_aggregate_event(
                registered_user, registered_user._events[-1]
            )

        event = test_domain.event_store.last_event_of_type(Renamed)
        assert event.name == "John Doe 9"

    @pytest.mark.eventstore
    def test_reading_the_last_event_of_type_with_multiple_events_in_stream(
        self, test_domain, registered_user
    ):
        for i in range(10):
            registered_user.rename(name=f"John Doe {i}")
            test_domain.event_store.store.append_aggregate_event(
                registered_user, registered_user._events[-1]
            )

        event = test_domain.event_store.last_event_of_type(Renamed, "user")
        assert event.name == "John Doe 9"

    @pytest.mark.eventstore
    def test_reading_the_last_event_of_type_with_multiple_events_in_different_stream(
        self, test_domain, registered_user
    ):
        for i in range(10):
            registered_user.rename(name=f"John Doe {i}")
            test_domain.event_store.store.append_aggregate_event(
                registered_user, registered_user._events[-1]
            )

        event = test_domain.event_store.last_event_of_type(Renamed, "group")
        assert event is None
