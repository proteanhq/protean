from __future__ import annotations

from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventSourcedAggregate
from protean.fields import String
from protean.fields.basic import Identifier


class User(BaseEventSourcedAggregate):
    email = String()
    name = String(max_length=50)


class Registered(BaseEvent):
    id = Identifier()
    email = String()

    class Meta:
        aggregate_cls = User


class Activated(BaseEvent):
    id = Identifier(required=True)

    class Meta:
        aggregate_cls = User


class Renamed(BaseEvent):
    id = Identifier(required=True)
    name = String(required=True, max_length=50)

    class Meta:
        aggregate_cls = User


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Registered)
    test_domain.register(Activated)
    test_domain.register(Renamed)


@pytest.fixture
def registered_user(test_domain):
    identifier = str(uuid4())

    event1 = Registered(id=identifier, email="john.doe@example.com")
    user = User(**event1.to_dict())
    test_domain.event_store.store.append_aggregate_event(user, event1)

    return user


@pytest.mark.eventstore
def test_reading_events_of_type_with_just_one_message(test_domain, registered_user):
    events = test_domain.event_store.events_of_type(Registered)
    assert len(events) == 1
    assert isinstance(events[0], Registered)


@pytest.mark.eventstore
def test_reading_events_of_type_with_other_events_present(test_domain, registered_user):
    test_domain.event_store.store.append_aggregate_event(
        registered_user, Activated(id=registered_user.id)
    )

    assert isinstance(test_domain.event_store.events_of_type(Registered)[0], Registered)
    assert isinstance(test_domain.event_store.events_of_type(Activated)[0], Activated)


@pytest.mark.eventstore
def test_reading_events_of_type_with_multiple_events(test_domain, registered_user):
    test_domain.event_store.store.append_aggregate_event(
        registered_user, Activated(id=registered_user.id)
    )

    for i in range(10):
        test_domain.event_store.store.append_aggregate_event(
            registered_user, Renamed(id=registered_user.id, name=f"John Doe {i}")
        )

    events = test_domain.event_store.events_of_type(Renamed)
    assert len(events) == 10
    assert events[-1].name == "John Doe 9"


@pytest.mark.eventstore
def test_reading_events_of_type_with_multiple_events_in_stream(
    test_domain, registered_user
):
    test_domain.event_store.store.append_aggregate_event(
        registered_user, Activated(id=registered_user.id)
    )

    for i in range(10):
        test_domain.event_store.store.append_aggregate_event(
            registered_user, Renamed(id=registered_user.id, name=f"John Doe {i}")
        )

    events = test_domain.event_store.events_of_type(Renamed, "user")
    assert len(events) == 10
    assert events[-1].name == "John Doe 9"


@pytest.mark.eventstore
def test_reading_events_of_type_with_multiple_events_in_different_stream(
    test_domain, registered_user
):
    test_domain.event_store.store.append_aggregate_event(
        registered_user, Activated(id=registered_user.id)
    )

    for i in range(10):
        test_domain.event_store.store.append_aggregate_event(
            registered_user, Renamed(id=registered_user.id, name=f"John Doe {i}")
        )

    events = test_domain.event_store.events_of_type(Renamed, "group")
    assert len(events) == 0
