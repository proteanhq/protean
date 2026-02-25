"""Generic filtering tests that run against all database providers.

Covers filter(), exclude(), lookups (exact, contains, in, gt, lt, etc.),
and query chaining operations on the DAO layer.
"""

from datetime import datetime, timedelta

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.queryset import QuerySet
from protean.exceptions import TooManyObjectsError
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
class TestDAOFilterFunctionality:
    def test_filtering_of_database_records(self, test_domain):
        # Add multiple entries to the database
        test_domain.repository_for(Person)._dao.create(
            first_name="John", last_name="Doe", age=22
        )
        test_domain.repository_for(Person)._dao.create(
            first_name="Jane", last_name="Doe", age=18
        )
        test_domain.repository_for(Person)._dao.create(
            first_name="Baby", last_name="Roe", age=2
        )

        # Filter by the last name
        people = test_domain.repository_for(Person)._dao.query.filter(last_name="Doe")
        assert people is not None
        assert people.total == 2
        assert len(people.items) == 2

    def test_traversal_of_filter_results(self, test_domain):
        """Test the traversal of the filter results"""
        for counter in range(1, 5):
            test_domain.repository_for(Person)._dao.create(
                id=str(counter), first_name=f"John{counter}", last_name="Doe"
            )

        people = (
            test_domain.repository_for(Person)._dao.query.limit(2).order_by("id").all()
        )
        assert people is not None
        assert people.total == 4
        assert len(people.items) == 2
        assert people.first.id == "1"
        assert people.has_next
        assert not people.has_prev

        people = (
            test_domain.repository_for(Person)
            ._dao.query.offset(2)
            .limit(2)
            .order_by("id")
            .all()
        )
        assert len(people.items) == 2
        assert people.first.id == "3"
        assert not people.has_next
        assert people.has_prev

    def test_entity_query_initialization(self, test_domain):
        """Test the initialization of a QuerySet"""
        dao = test_domain.repository_for(Person)._dao
        query = dao.query

        assert query is not None
        assert isinstance(query, QuerySet)
        assert query._criteria == QuerySet(dao, test_domain, Person)._criteria

    def test_filter_initialization_of_query_from_entity(self, test_domain):
        filters = [
            test_domain.repository_for(Person)._dao.query.filter(first_name="Murdock"),
            test_domain.repository_for(Person)
            ._dao.query.filter(first_name="Jean")
            .filter(last_name="John"),
            test_domain.repository_for(Person)._dao.query.offset(1),
            test_domain.repository_for(Person)._dao.query.limit(25),
            test_domain.repository_for(Person)._dao.query.order_by("first_name"),
            test_domain.repository_for(Person)._dao.query.exclude(first_name="Bravo"),
        ]

        for filter in filters:
            assert isinstance(filter, QuerySet)

    def test_that_chaining_filters_returns_a_queryset_for_further_chaining(
        self, test_domain
    ):
        person_query = test_domain.repository_for(Person)._dao.query.filter(
            first_name="Murdock"
        )
        filters = [
            person_query,
            test_domain.repository_for(Person)
            ._dao.query.filter(first_name="Jean")
            .filter(last_name="John"),
            person_query.offset(5 * 5),
            person_query.limit(5),
            person_query.order_by("first_name"),
            person_query.exclude(last_name="Murdock"),
        ]

        for filter in filters:
            assert isinstance(filter, QuerySet)

    def test_filter_by_chaining_example_1(self, test_domain):
        # Add multiple entries to the DB
        test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Murdock", age=7, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="3", first_name="Jean", age=3, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="4", first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Person attributes
        query = (
            test_domain.repository_for(Person)
            ._dao.query.filter(first_name="Jean")
            .filter(last_name="John")
            .filter(age=3)
        )
        people = query.all()

        assert people is not None
        assert people.total == 1
        assert len(people.items) == 1

        person = people.first
        assert person.id == "3"

    def test_filter_by_chaining_example_2(self, test_domain):
        # Add multiple entries to the DB
        test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Murdock", age=7, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="3", first_name="Jean", age=3, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="4", first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Person attributes
        query = test_domain.repository_for(Person)._dao.query.filter(last_name="John")
        people = query.all()

        assert people is not None
        assert people.total == 2
        assert len(people.items) == 2

        person = people.first
        assert person.id == "2"

    def test_filter_by_chaining_example_3(self, test_domain):
        # Add multiple entries to the DB
        test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Murdock", age=7, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="3", first_name="Jean", age=3, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="4", first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter with ordering
        query = (
            test_domain.repository_for(Person)
            ._dao.query.filter(last_name="John")
            .order_by("age")
        )
        people = query.all()

        assert people is not None
        assert people.total == 2
        assert len(people.items) == 2

        person = people.first
        assert person.id == "3"

    def test_results_retrieved_with_filter(self, test_domain):
        # Add multiple entries to the DB
        test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Murdock", age=7, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="3", first_name="Jean", age=3, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="4", first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by the LastName
        people = test_domain.repository_for(Person)._dao.query.filter(last_name="John")
        assert people is not None
        assert people.total == 2
        assert len(people.items) == 2

        # Order the results by age
        people = (
            test_domain.repository_for(Person)
            ._dao.query.filter(last_name="John")
            .order_by("-age")
        )
        assert people is not None
        assert people.first.age == 7
        assert people.first.first_name == "Murdock"

    def test_results_retrieved_after_exclusion(self, test_domain):
        # Add multiple entries to the DB
        test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Murdock", age=7, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="3", first_name="Jean", age=3, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="4", first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Exclusion
        people = test_domain.repository_for(Person)._dao.query.exclude(last_name="John")
        assert people is not None
        assert people.total == 1
        assert len(people.items) == 1
        assert people.first.age == 6
        assert people.first.first_name == "Bart"

    def test_results_retrieved_after_multiple_value_exclusion(self, test_domain):
        # Add multiple entries to the DB
        test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Murdock", age=7, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="3", first_name="Jean", age=3, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="4", first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by the first_name
        people = test_domain.repository_for(Person)._dao.query.exclude(
            first_name__in=["Murdock", "Jean"]
        )
        assert people is not None
        assert people.total == 1
        assert len(people.items) == 1
        assert people.first.age == 6
        assert people.first.first_name == "Bart"

    def test_error_on_finding_multiple_results(self, test_domain):
        test_domain.repository_for(Person)._dao.create(
            id="2346", first_name="Johnny1", last_name="Bravo", age=8
        )
        test_domain.repository_for(Person)._dao.create(
            id="2347", first_name="Johnny1", last_name="Gravo", age=6
        )

        with pytest.raises(TooManyObjectsError):
            test_domain.repository_for(Person)._dao.find_by(first_name="Johnny1")


@pytest.mark.basic_storage
class TestDAOLookups:
    def test_comparisons_using_different_operators(self, test_domain):
        # Add multiple entries to the DB
        test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Murdock", age=7, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="3", first_name="Jean", age=3, last_name="john"
        )
        test_domain.repository_for(Person)._dao.create(
            id="4", first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by various operators
        people_gte = test_domain.repository_for(Person)._dao.query.filter(age__gte=3)
        people_datetime_gte = test_domain.repository_for(Person)._dao.query.filter(
            created_at__gte=datetime.now() - timedelta(hours=24)
        )
        people_lte = test_domain.repository_for(Person)._dao.query.filter(age__lte=6)
        people_gt = test_domain.repository_for(Person)._dao.query.filter(age__gt=3)
        people_lt = test_domain.repository_for(Person)._dao.query.filter(age__lt=6)
        people_in = test_domain.repository_for(Person)._dao.query.filter(
            first_name__in=["Jean", "Bart", "Nobody"]
        )
        people_exact = test_domain.repository_for(Person)._dao.query.filter(
            last_name__exact="John"
        )
        people_iexact = test_domain.repository_for(Person)._dao.query.filter(
            last_name__iexact="John"
        )

        assert people_gte.total == 3
        assert people_datetime_gte.total == 3
        assert people_lte.total == 2
        assert people_gt.total == 2
        assert people_lt.total == 1
        assert people_in.total == 2
        assert people_exact.total == 1
        assert people_iexact.total == 2

    def test_filtering_using_contains(self, test_domain):
        # Add multiple entries to the DB
        test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Murdock", age=7, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="3", first_name="Jean", age=3, last_name="john"
        )
        test_domain.repository_for(Person)._dao.create(
            id="4", first_name="Bart", age=6, last_name="Carrie"
        )

        people_contains = test_domain.repository_for(Person)._dao.query.filter(
            last_name__contains="Joh"
        )
        people_icontains = test_domain.repository_for(Person)._dao.query.filter(
            last_name__icontains="Joh"
        )

        assert people_contains.total == 1
        assert people_icontains.total == 2

    def test_exception_on_usage_of_unsupported_comparison_operator(self, test_domain):
        # Add multiple entries to the DB
        test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Murdock", age=7, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="3", first_name="Jean", age=3, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            id="4", first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by unsupported operator
        with pytest.raises(NotImplementedError):
            test_domain.repository_for(Person)._dao.query.filter(age__notexact=3).all()


@pytest.mark.basic_storage
class TestDAOLookupRegistration:
    """Test lookup class registration and instantiation"""

    @pytest.fixture
    def sample_lookup_cls(self):
        from protean.adapters.repository.sqlalchemy import SAProvider
        from protean.port.dao import BaseLookup

        @SAProvider.register_lookup
        class SampleLookup(BaseLookup):
            """A simple implementation of lookup class"""

            lookup_name = "sample"

            def as_expression(self):
                return "%s %s %s" % (
                    self.process_source(),
                    "<<<>>>",
                    self.process_target(),
                )

        return SampleLookup

    def test_initialization_of_a_lookup_object(self, sample_lookup_cls):
        lookup = sample_lookup_cls("src", "trg")
        assert lookup.as_expression() == "src <<<>>> trg"

    def test_registration_of_a_lookup_to_an_adapter(self, sample_lookup_cls):
        from protean.adapters.repository.sqlalchemy import SAProvider

        assert SAProvider.get_lookups().get("sample") == sample_lookup_cls
