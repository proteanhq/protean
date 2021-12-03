import pytest

from protean import BaseEventSourcedAggregate
from protean.fields import Identifier, Integer, String
from protean.utils import fully_qualified_name


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach identifier
    name = String()
    age = Integer()


def test_registering_an_event_sourced_aggregate_manually(test_domain):
    try:
        test_domain.register(User)
    except Exception:
        pytest.fail("Failed to register an Event Sourced Aggregate")

    assert fully_qualified_name(User) in test_domain.registry.event_sourced_aggregates


def test_registering_an_event_sourced_aggregate_via_annotation(test_domain):
    try:

        @test_domain.event_sourced_aggregate
        class Person:
            id = Identifier(identifier=True)  # FIXME Auto-attach identifier
            name = String()
            age = Integer()

    except Exception:
        pytest.fail("Failed to register an Event Sourced Aggregate via annotation")

    assert fully_qualified_name(Person) in test_domain.registry.event_sourced_aggregates
