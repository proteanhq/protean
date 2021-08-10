from datetime import datetime, timedelta

import pytest

from protean.core.queryset import QuerySet
from protean.exceptions import ObjectNotFoundError, TooManyObjectsError

from .elements import Person, PersonRepository, User


class TestDAORetrievalFunctionality:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonRepository, aggregate_cls=Person)
        test_domain.register(User)

    @pytest.fixture
    def persisted_person(self, test_domain):
        person = test_domain.get_dao(Person).create(
            id=1234, first_name="John", last_name="Doe"
        )
        return person

    def test_filtering_of_database_records(self, test_domain):
        # Add multiple entries to the database
        test_domain.get_dao(Person).create(first_name="John", last_name="Doe", age=22)
        test_domain.get_dao(Person).create(first_name="Jane", last_name="Doe", age=18)
        test_domain.get_dao(Person).create(first_name="Baby", last_name="Roe", age=2)

        # Filter by the last name
        people = test_domain.get_dao(Person).query.filter(last_name="Doe")
        assert people is not None
        assert people.total == 2
        assert len(people.items) == 2

        # Order the results by age
        people = test_domain.get_dao(Person).query.order_by("age")
        assert people is not None
        assert people.first.age == 2
        assert people.first.first_name == "Baby"

    def test_traversal_of_filter_results(self, test_domain):
        """ Test the traversal of the filter results"""
        for counter in range(1, 5):
            test_domain.get_dao(Person).create(
                id=counter, first_name=f"John{counter}", last_name="Doe"
            )

        people = test_domain.get_dao(Person).query.limit(2).order_by("id")
        assert people is not None
        assert people.total == 4
        assert len(people.items) == 2
        assert people.first.id == 1
        assert people.has_next
        assert not people.has_prev

        people = (
            test_domain.get_dao(Person).query.offset(2).limit(2).order_by("id").all()
        )
        assert len(people.items) == 2
        assert people.first.id == 3
        assert not people.has_next
        assert people.has_prev

    def test_entity_retrieval_by_its_primary_key(self, test_domain, persisted_person):
        """Test Entity Retrieval by its primary key"""
        dog = test_domain.get_dao(Person).get(persisted_person.id)
        assert dog is not None
        assert dog.id == 1234

    def test_failed_entity_retrieval_by_its_primary_key(self, test_domain):
        """Test failed Entity Retrieval by its primary key"""
        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).get(1235)

    def test_entity_retrieval_by_specific_column_value(
        self, test_domain, persisted_person
    ):
        dog = test_domain.get_dao(Person).find_by(first_name="John")
        assert dog is not None
        assert dog.id == 1234

    def test_failed_entity_retrieval_by_column_value(
        self, test_domain, persisted_person
    ):
        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).find_by(first_name="JohnnyChase")

    def test_entity_retrieval_by_multiple_column_values(self, test_domain):
        test_domain.get_dao(Person).create(
            id=2346, first_name="Johnny1", last_name="Bravo", age=8
        )
        test_domain.get_dao(Person).create(
            id=2347, first_name="Johnny2", last_name="Bravo", age=6
        )

        dog = test_domain.get_dao(Person).find_by(first_name="Johnny1", age=8)
        assert dog is not None
        assert dog.id == 2346

    def test_failed_entity_retrieval_by_multiple_column_values(self, test_domain):
        test_domain.get_dao(Person).create(
            id=2346, first_name="Johnny1", last_name="Bravo", age=8
        )
        test_domain.get_dao(Person).create(
            id=2347, first_name="Johnny2", last_name="Bravo", age=6
        )

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).find_by(first_name="Johnny1", age=6)

    def test_error_on_finding_multiple_results(self, test_domain):
        test_domain.get_dao(Person).create(
            id=2346, first_name="Johnny1", last_name="Bravo", age=8
        )
        test_domain.get_dao(Person).create(
            id=2347, first_name="Johnny1", last_name="Gravo", age=6
        )

        with pytest.raises(TooManyObjectsError):
            test_domain.get_dao(Person).find_by(first_name="Johnny1")

    def test_entity_query_initialization(self, test_domain):
        """Test the initialization of a QuerySet"""
        dao = test_domain.get_dao(Person)
        query = dao.query

        assert query is not None
        assert isinstance(query, QuerySet)
        assert query._criteria == QuerySet(dao, test_domain, Person)._criteria

    def test_filter_initialization_of_query_from_entity(self, test_domain):
        filters = [
            test_domain.get_dao(Person).query.filter(first_name="Murdock"),
            test_domain.get_dao(Person)
            .query.filter(first_name="Jean")
            .filter(last_name="John"),
            test_domain.get_dao(Person).query.offset(1),
            test_domain.get_dao(Person).query.limit(25),
            test_domain.get_dao(Person).query.order_by("first_name"),
            test_domain.get_dao(Person).query.exclude(first_name="Bravo"),
        ]

        for filter in filters:
            assert isinstance(filter, QuerySet)

    def test_that_chaining_filters_returns_a_queryset_for_further_chaining(
        self, test_domain
    ):
        person_query = test_domain.get_dao(Person).query.filter(name="Murdock")
        filters = [
            person_query,
            test_domain.get_dao(Person)
            .query.filter(first_name="Jean")
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
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Person attributes
        query = (
            test_domain.get_dao(Person)
            .query.filter(first_name="Jean")
            .filter(last_name="John")
            .filter(age=3)
        )
        people = query.all()

        assert people is not None
        assert people.total == 1
        assert len(people.items) == 1

        person = people.first
        assert person.id == 3

    def test_filter_by_chaining_example_2(self, test_domain):
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Person attributes
        query = test_domain.get_dao(Person).query.filter(last_name="John")
        people = query.all()

        assert people is not None
        assert people.total == 2
        assert len(people.items) == 2

        person = people.first
        assert person.id == 2

    def test_filter_by_chaining_example_3(self, test_domain):
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Dog attributes
        query = (
            test_domain.get_dao(Person).query.filter(last_name="John").order_by("age")
        )
        people = query.all()

        assert people is not None
        assert people.total == 2
        assert len(people.items) == 2

        person = people.first
        assert person.id == 3

    def test_results_retrieved_with_filter(self, test_domain):
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by the LastName
        people = test_domain.get_dao(Person).query.filter(last_name="John")
        assert people is not None
        assert people.total == 2
        assert len(people.items) == 2

        # Order the results by age
        people = (
            test_domain.get_dao(Person).query.filter(last_name="John").order_by("-age")
        )
        assert people is not None
        assert people.first.age == 7
        assert people.first.first_name == "Murdock"

    def test_results_retrieved_after_exclusion(self, test_domain):
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Exclusion
        dogs = test_domain.get_dao(Person).query.exclude(last_name="John")
        assert dogs is not None
        assert dogs.total == 1
        assert len(dogs.items) == 1
        assert dogs.first.age == 6
        assert dogs.first.first_name == "Bart"

    def test_results_retrieved_after_multiple_value_exclusion(self, test_domain):
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by the first_name
        people = test_domain.get_dao(Person).query.exclude(
            first_name__in=["Murdock", "Jean"]
        )
        assert people is not None
        assert people.total == 1
        assert len(people.items) == 1
        assert people.first.age == 6
        assert people.first.first_name == "Bart"

    def test_comparisons_using_different_operators(self, test_domain):
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="john"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by the Owner
        people_gte = test_domain.get_dao(Person).query.filter(age__gte=3)
        people_datetime_gte = test_domain.get_dao(Person).query.filter(
            created_at__gte=datetime.now() - timedelta(hours=24)
        )
        people_lte = test_domain.get_dao(Person).query.filter(age__lte=6)
        people_gt = test_domain.get_dao(Person).query.filter(age__gt=3)
        people_lt = test_domain.get_dao(Person).query.filter(age__lt=6)
        people_in = test_domain.get_dao(Person).query.filter(
            first_name__in=["Jean", "Bart", "Nobody"]
        )
        people_exact = test_domain.get_dao(Person).query.filter(last_name__exact="John")
        people_iexact = test_domain.get_dao(Person).query.filter(
            last_name__iexact="John"
        )
        people_contains = test_domain.get_dao(Person).query.filter(
            last_name__contains="Joh"
        )
        people_icontains = test_domain.get_dao(Person).query.filter(
            last_name__icontains="Joh"
        )

        assert people_gte.total == 3
        assert people_datetime_gte.total == 3
        assert people_lte.total == 2
        assert people_gt.total == 2
        assert people_lt.total == 1
        assert people_in.total == 2
        assert people_exact.total == 1
        assert people_iexact.total == 2
        assert people_contains.total == 1
        assert people_icontains.total == 2

    def test_exception_on_usage_of_unsupported_comparison_operator(self, test_domain):
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by the Owner
        with pytest.raises(NotImplementedError):
            test_domain.get_dao(Person).query.filter(age__notexact=3).all()
