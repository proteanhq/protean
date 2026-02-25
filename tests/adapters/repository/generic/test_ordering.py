"""Generic ordering tests that run against all database providers.

Covers ORDER BY support for query results.
"""

from datetime import datetime

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import DateTime, Integer, String


class Person(BaseAggregate):
    first_name: String(max_length=50, required=True)
    last_name: String(max_length=50, required=True)
    age: Integer(default=21)
    created_at: DateTime(default=datetime.now())


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)


@pytest.mark.basic_storage
class TestDAOOrderingFunctionality:
    def test_ordering_by_ascending(self, test_domain):
        test_domain.repository_for(Person)._dao.create(
            first_name="John", last_name="Doe", age=22
        )
        test_domain.repository_for(Person)._dao.create(
            first_name="Jane", last_name="Doe", age=18
        )
        test_domain.repository_for(Person)._dao.create(
            first_name="Baby", last_name="Roe", age=2
        )

        # Order the results by age
        people = test_domain.repository_for(Person)._dao.query.order_by("age")
        assert people is not None
        assert people.first.age == 2
        assert people.first.first_name == "Baby"

    def test_ordering_by_descending(self, test_domain):
        test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Murdock", age=7, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="3", first_name="Jean", age=3, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="4", first_name="Bart", age=6, last_name="Carrie"
        )

        # Order the results by age descending
        people = (
            test_domain.repository_for(Person)
            ._dao.query.filter(last_name="John")
            .order_by("-age")
        )
        assert people is not None
        assert people.first.age == 7
        assert people.first.first_name == "Murdock"

    def test_ordering_with_filter_chaining(self, test_domain):
        test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Murdock", age=7, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="3", first_name="Jean", age=3, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="4", first_name="Bart", age=6, last_name="Carrie"
        )

        query = (
            test_domain.repository_for(Person)
            ._dao.query.filter(last_name="John")
            .order_by("age")
        )
        people = query.all()

        assert people is not None
        assert people.total == 2
        assert people.first.id == "3"

    def test_ordering_by_id(self, test_domain):
        for counter in range(1, 5):
            test_domain.repository_for(Person)._dao.create(
                id=str(counter), first_name=f"John{counter}", last_name="Doe"
            )

        people = test_domain.repository_for(Person)._dao.query.order_by("id").all()
        assert people is not None
        assert people.first.id == "1"

        people = test_domain.repository_for(Person)._dao.query.order_by("-id").all()
        assert people.first.id == "4"
