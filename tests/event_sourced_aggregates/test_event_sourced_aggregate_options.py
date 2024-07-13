import pytest

from protean import BaseEventSourcedAggregate
from protean.fields import Integer, String


class User(BaseEventSourcedAggregate):
    name = String()
    age = Integer()


class AdminUser(BaseEventSourcedAggregate):
    name = String()


class Person(BaseEventSourcedAggregate):
    name = String()
    age = Integer()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(AdminUser)
    test_domain.register(Person, stream_category="people")


def test_stream_category_option_of_an_event_sourced_aggregate():
    assert User.meta_.stream_category == "user"

    # Verify snake-casing the Aggregate name
    assert AdminUser.meta_.stream_category == "admin_user"

    # Verify manually set stream_category
    assert Person.meta_.stream_category == "people"


def test_stream_category_option_of_an_event_sourced_aggregate_defined_via_annotation(
    test_domain,
):
    @test_domain.event_sourced_aggregate
    class Adult(BaseEventSourcedAggregate):
        name = String()
        age = Integer()

    assert Adult.meta_.stream_category == "adult"

    @test_domain.event_sourced_aggregate(stream_category="children")
    class Child(BaseEventSourcedAggregate):
        name = String()
        age = Integer()

    assert Child.meta_.stream_category == "children"
