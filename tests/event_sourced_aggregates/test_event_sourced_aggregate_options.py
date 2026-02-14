import pytest

from protean.core.aggregate import BaseAggregate


class User(BaseAggregate):
    name: str | None = None
    age: int | None = None


class AdminUser(BaseAggregate):
    name: str | None = None


class Person(BaseAggregate):
    name: str | None = None
    age: int | None = None


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
        name: str | None = None
        age: int | None = None

    assert Adult.meta_.stream_category == "test::adult"

    @test_domain.aggregate(is_event_sourced=True, stream_category="children")
    class Child(BaseAggregate):
        name: str | None = None
        age: int | None = None

    assert Child.meta_.stream_category == "test::children"
