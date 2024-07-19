import pytest

from protean import BaseAggregate
from protean.fields import Integer, String


class User(BaseAggregate):
    name = String()
    age = Integer()


class AdminUser(BaseAggregate):
    name = String()


class Person(BaseAggregate):
    name = String()
    age = Integer()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(AdminUser, is_event_sourced=True)
    test_domain.register(Person, is_event_sourced=True, stream_category="people")


def test_stream_category_option_of_an_event_sourced_aggregate():
    assert User.meta_.stream_category == "test::user"

    # Verify snake-casing the Aggregate name
    assert AdminUser.meta_.stream_category == "test::admin_user"

    # Verify manually set stream_category
    assert Person.meta_.stream_category == "test::people"


def test_stream_category_option_of_an_event_sourced_aggregate_defined_via_annotation(
    test_domain,
):
    @test_domain.aggregate(is_event_sourced=True)
    class Adult(BaseAggregate):
        name = String()
        age = Integer()

    assert Adult.meta_.stream_category == "test::adult"

    @test_domain.aggregate(is_event_sourced=True, stream_category="children")
    class Child(BaseAggregate):
        name = String()
        age = Integer()

    assert Child.meta_.stream_category == "test::children"
