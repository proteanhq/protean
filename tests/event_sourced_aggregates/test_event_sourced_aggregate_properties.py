from uuid import uuid4

import pytest

from protean import BaseEventSourcedAggregate
from protean.exceptions import NotSupportedError
from protean.fields import Integer, String


class User(BaseEventSourcedAggregate):
    name = String()
    age = Integer()


def test_event_sourced_aggregate_cannot_be_initialized():
    with pytest.raises(NotSupportedError) as exc:
        BaseEventSourcedAggregate()

    assert str(exc.value) == "BaseEventSourcedAggregate cannot be instantiated"


class TestEventSourcedAggregateEquivalence:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User)
        test_domain.init(traverse=False)

    def test_event_sourced_aggregate_are_not_equivalent_based_on_data(test_domain):
        user1 = User(name="John Doe", age=25)
        user2 = User(name="John Doe", age=25)

        assert user1 != user2

    def test_event_sourced_aggregate_equivalence_with_same_id(test_domain):
        user1 = User(name="John Doe", age=25)
        user2 = User(user1.to_dict())
        user3 = User(name="Jane Doe", age=25, id=user1.id)

        assert user1 == user2 == user3

    def test_event_sourced_aggregate_equivalence_with_different_element(test_domain):
        class Person(User):
            pass

        identifier = str(uuid4())
        person1 = Person(name="John Doe", age=25, id=identifier)
        user2 = User(name="John Doe", age=25, id=identifier)

        assert person1 != user2


def test_event_sourced_aggregate_hash(test_domain):
    test_domain.register(User)

    user1 = User(name="John Doe", age=25)
    assert hash(user1) == hash(user1.id)
