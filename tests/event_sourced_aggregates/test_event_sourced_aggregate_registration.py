import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String
from protean.utils import fully_qualified_name


class User(BaseAggregate):
    name = String()
    age = Integer()


def test_registering_an_event_sourced_aggregate_manually(test_domain):
    try:
        test_domain.register(User, is_event_sourced=True)
    except Exception:
        pytest.fail("Failed to register an Event Sourced Aggregate")

    assert fully_qualified_name(User) in test_domain.registry.aggregates


def test_registering_an_event_sourced_aggregate_via_annotation(test_domain):
    try:

        @test_domain.aggregate(is_event_sourced=True)
        class Person:
            name = String()
            age = Integer()

    except Exception:
        pytest.fail("Failed to register an Event Sourced Aggregate via annotation")

    assert fully_qualified_name(Person) in test_domain.registry.aggregates
