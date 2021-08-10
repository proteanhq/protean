from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from sqlalchemy.orm.session import Session

from protean.core.queryset import Q, QuerySet
from protean.exceptions import ObjectNotFoundError, TooManyObjectsError, ValidationError

from .elements import Person, User


@pytest.mark.postgresql
class TestDAO:
    """This class holds tests for DAO class"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)

    def test_successful_initialization_of_dao(self, test_domain):
        test_domain.get_dao(Person).query.all()
        provider = test_domain.get_provider("default")
        conn = provider.get_connection()
        assert conn is not None
        assert isinstance(conn, Session)

    def test_that_escaped_quotes_in_values_are_handled_properly(self, test_domain):
        test_domain.get_dao(Person).create(
            first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.get_dao(Person).create(
            first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.get_dao(Person).create(
            first_name="Aramis", last_name="Musketeer", age=4
        )

        person1 = test_domain.get_dao(Person).create(
            first_name="d'Artagnan1", last_name="John", age=5
        )
        person2 = test_domain.get_dao(Person).create(
            first_name="d'Artagnan2", last_name="John", age=5
        )
        person3 = test_domain.get_dao(Person).create(
            first_name='d"Artagnan3', last_name="John", age=5
        )
        person4 = test_domain.get_dao(Person).create(
            first_name='d"Artagnan4', last_name="John", age=5
        )

        assert all(
            person is not None for person in [person1, person2, person3, person4]
        )


@pytest.mark.postgresql
class TestDAODeleteFunctionality:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)

    def test_delete_an_object_in_repository_by_id(self, test_domain):
        """ Delete an object in the repository by ID"""
        identifier = uuid4()
        person = test_domain.get_dao(Person).create(
            id=identifier, first_name="John", last_name="Doe", age=22
        )

        persisted_person = test_domain.get_dao(Person).get(identifier)
        assert persisted_person is not None

        deleted_person = test_domain.get_dao(Person).delete(person)
        assert deleted_person is not None
        assert deleted_person.state_.is_destroyed is True

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).get(identifier)

    def test_delete_all_records_in_repository(self, test_domain):
        """Delete all objects in a repository"""
        test_domain.get_dao(Person).create(
            first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.get_dao(Person).create(
            first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.get_dao(Person).create(
            first_name="Aramis", last_name="Musketeer", age=4
        )
        test_domain.get_dao(Person).create(
            first_name="dArtagnan", last_name="Musketeer", age=5
        )

        person_records = test_domain.get_dao(Person).query.filter(Q())
        assert person_records.total == 4

        test_domain.get_dao(Person).delete_all()

        person_records = test_domain.get_dao(Person).query.filter(Q())
        assert person_records.total == 0

    def test_deleting_a_persisted_entity(self, test_domain):
        """ Delete an object in the repository by ID"""
        identifier = uuid4()
        person = test_domain.get_dao(Person).create(
            id=identifier, first_name="Jim", last_name="Carrey"
        )
        deleted_person = test_domain.get_dao(Person).delete(person)
        assert deleted_person is not None
        assert deleted_person.state_.is_destroyed is True

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).get(identifier)

    def test_deleting_all_entities_of_a_type(self, test_domain):
        test_domain.get_dao(Person).create(
            first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.get_dao(Person).create(
            first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.get_dao(Person).create(
            first_name="Aramis", last_name="Musketeer", age=4
        )
        test_domain.get_dao(Person).create(
            first_name="dArtagnan", last_name="Musketeer", age=5
        )

        people = test_domain.get_dao(Person).query.all()
        assert people.total == 4

        test_domain.get_dao(Person).delete_all()

        people = test_domain.get_dao(Person).query.all()
        assert people.total == 0

    def test_deleting_all_records_of_a_type_satisfying_a_filter(self, test_domain):
        identifier1 = uuid4()
        identifier2 = uuid4()
        identifier3 = uuid4()
        identifier4 = uuid4()
        test_domain.get_dao(Person).create(
            id=identifier1, first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.get_dao(Person).create(
            id=identifier2, first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.get_dao(Person).create(
            id=identifier3, first_name="Aramis", last_name="Musketeer", age=4
        )
        test_domain.get_dao(Person).create(
            id=identifier4, first_name="d'Artagnan", last_name="Musketeer", age=5
        )

        # Perform update
        deleted_count = test_domain.get_dao(Person).query.filter(age__gt=3).delete_all()

        # Query and check if only the relevant records have been deleted
        assert deleted_count == 2

        person1 = test_domain.get_dao(Person).get(identifier1)
        person2 = test_domain.get_dao(Person).get(identifier2)

        assert person1 is not None
        assert person2 is not None

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).get(identifier3)

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).get(identifier4)

    def test_deleting_records_satisfying_a_filter(self, test_domain):
        identifier1 = uuid4()
        identifier2 = uuid4()
        identifier3 = uuid4()
        identifier4 = uuid4()
        test_domain.get_dao(Person).create(
            id=identifier1, first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.get_dao(Person).create(
            id=identifier2, first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.get_dao(Person).create(
            id=identifier3, first_name="Aramis", last_name="Musketeer", age=4
        )
        test_domain.get_dao(Person).create(
            id=identifier4, first_name="d'Artagnan", last_name="Musketeer", age=5
        )

        # Perform update
        deleted_count = test_domain.get_dao(Person).query.filter(age__gt=3).delete()

        # Query and check if only the relevant records have been updated
        assert deleted_count == 2
        assert test_domain.get_dao(Person).query.all().total == 2

        assert test_domain.get_dao(Person).get(identifier1) is not None
        assert test_domain.get_dao(Person).get(identifier2) is not None
        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).get(identifier3)

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).get(identifier4)


@pytest.mark.postgresql
class TestDAORetrievalFunctionality:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)

    @pytest.fixture
    def identifier(self):
        return uuid4()

    @pytest.fixture
    def persisted_person(self, test_domain, identifier):
        person = test_domain.get_dao(Person).create(
            id=identifier, first_name="John", last_name="Doe"
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
        identifiers = [uuid4() for i in range(1, 5)]
        timestamp = datetime.now()
        for counter in range(1, 5):
            test_domain.get_dao(Person).create(
                id=identifiers[counter - 1],
                first_name=f"John{counter}",
                last_name="Doe",
                created_at=timestamp + timedelta(minutes=counter),
            )

        people = test_domain.get_dao(Person).query.limit(2).order_by("created_at").all()
        assert people is not None
        assert people.total == 4
        assert len(people.items) == 2
        assert people.first.id == identifiers[0]
        assert people.has_next
        assert not people.has_prev

        people = (
            test_domain.get_dao(Person)
            .query.offset(2)
            .limit(2)
            .order_by("created_at")
            .all()
        )
        assert len(people.items) == 2
        assert people.first.id == identifiers[2]
        assert not people.has_next
        assert people.has_prev

    def test_entity_retrieval_by_its_primary_key(
        self, test_domain, identifier, persisted_person
    ):
        """Test Entity Retrieval by its primary key"""
        person = test_domain.get_dao(Person).get(persisted_person.id)
        assert person is not None
        assert person.id == identifier

    def test_failed_entity_retrieval_by_its_primary_key(self, test_domain):
        """Test failed Entity Retrieval by its primary key"""
        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).get(uuid4())

    def test_entity_retrieval_by_specific_column_value(
        self, test_domain, identifier, persisted_person
    ):
        person = test_domain.get_dao(Person).find_by(first_name="John")
        assert person is not None
        assert person.id == identifier

    def test_failed_entity_retrieval_by_column_value(
        self, test_domain, persisted_person
    ):
        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).find_by(first_name="JohnnyChase")

    def test_entity_retrieval_by_multiple_column_values(self, test_domain):
        identifier1 = uuid4()
        identifier2 = uuid4()
        test_domain.get_dao(Person).create(
            id=identifier1, first_name="Johnny1", last_name="Bravo", age=8
        )
        test_domain.get_dao(Person).create(
            id=identifier2, first_name="Johnny2", last_name="Bravo", age=6
        )

        dog = test_domain.get_dao(Person).find_by(first_name="Johnny1", age=8)
        assert dog is not None
        assert dog.id == identifier1

    def test_failed_entity_retrieval_by_multiple_column_values(self, test_domain):
        test_domain.get_dao(Person).create(
            first_name="Johnny1", last_name="Bravo", age=8
        )
        test_domain.get_dao(Person).create(
            first_name="Johnny2", last_name="Bravo", age=6
        )

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).find_by(first_name="Johnny1", age=6)

    def test_error_on_finding_multiple_results(self, test_domain):
        test_domain.get_dao(Person).create(
            first_name="Johnny1", last_name="Bravo", age=8
        )
        test_domain.get_dao(Person).create(
            first_name="Johnny1", last_name="Gravo", age=6
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
        identifier1 = uuid4()
        identifier2 = uuid4()
        identifier3 = uuid4()
        test_domain.get_dao(Person).create(
            id=identifier1, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=identifier2, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=identifier3, first_name="Bart", age=6, last_name="Carrie"
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
        assert person.id == identifier2

    def test_filter_by_chaining_example_2(self, test_domain):
        # Add multiple entries to the DB
        identifier1 = uuid4()
        identifier2 = uuid4()
        identifier3 = uuid4()
        test_domain.get_dao(Person).create(
            id=identifier1, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=identifier2, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=identifier3, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Person attributes
        query = test_domain.get_dao(Person).query.filter(last_name="John")
        people = query.all()

        assert people is not None
        assert people.total == 2
        assert len(people.items) == 2

        person = people.first
        assert person.id == identifier1

    def test_filter_by_chaining_example_3(self, test_domain):
        # Add multiple entries to the DB
        identifier1 = uuid4()
        identifier2 = uuid4()
        identifier3 = uuid4()
        test_domain.get_dao(Person).create(
            id=identifier1, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=identifier2, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=identifier3, first_name="Bart", age=6, last_name="Carrie"
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
        assert person.id == identifier2

    def test_results_retrieved_with_filter(self, test_domain):
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(first_name="Jean", age=3, last_name="John")
        test_domain.get_dao(Person).create(first_name="Bart", age=6, last_name="Carrie")

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
            first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(first_name="Jean", age=3, last_name="John")
        test_domain.get_dao(Person).create(first_name="Bart", age=6, last_name="Carrie")

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
            first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(first_name="Jean", age=3, last_name="John")
        test_domain.get_dao(Person).create(first_name="Bart", age=6, last_name="Carrie")

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
            first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(first_name="Jean", age=3, last_name="john")
        test_domain.get_dao(Person).create(first_name="Bart", age=6, last_name="Carrie")

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
        test_domain.get_dao(Person).create(
            first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(first_name="Jean", age=3, last_name="john")
        test_domain.get_dao(Person).create(first_name="Bart", age=6, last_name="Carrie")

        people_contains = test_domain.get_dao(Person).query.filter(
            last_name__contains="Joh"
        )
        people_icontains = test_domain.get_dao(Person).query.filter(
            last_name__icontains="Joh"
        )

        assert people_contains.total == 1
        assert people_icontains.total == 2

    def test_exception_on_usage_of_unsupported_comparison_operator(self, test_domain):
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(first_name="Jean", age=3, last_name="John")
        test_domain.get_dao(Person).create(first_name="Bart", age=6, last_name="Carrie")

        # Filter by the Owner
        with pytest.raises(NotImplementedError):
            test_domain.get_dao(Person).query.filter(age__notexact=3).all()


@pytest.mark.postgresql
class TestDAOSaveFunctionality:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)

    def test_creation_throws_error_on_missing_fields(self, test_domain):
        """ Add an entity to the repository missing a required attribute"""
        with pytest.raises(ValidationError) as err:
            test_domain.get_dao(Person).create(last_name="Doe")

        assert err.value.messages == {"first_name": ["is required"]}

    def test_entity_persistence_with_create_method_and_fetch(self, test_domain):
        identifier = uuid4()
        person = test_domain.get_dao(Person).create(
            id=identifier, first_name="John", last_name="Doe"
        )
        assert person is not None
        assert person.first_name == "John"
        assert person.last_name == "Doe"
        assert person.age == 21

        db_person = test_domain.get_dao(Person).get(identifier)
        assert db_person is not None
        assert db_person == person

    def test_multiple_persistence_for_an_aggregate(self, test_domain):
        """Test that save can be invoked again on an already existing entity, to update values"""
        person = Person(first_name="Johnny", last_name="John")
        test_domain.get_dao(Person).save(person)

        person.last_name = "Janey"
        test_domain.get_dao(Person).save(person)

        test_domain.get_dao(Person).get(person.id)
        assert person.last_name == "Janey"


@pytest.mark.postgresql
class TestDAOUpdateFunctionality:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)

    def test_update_an_existing_entity_in_the_repository(self, test_domain):
        identifier = uuid4()
        person = test_domain.get_dao(Person).create(
            id=identifier, first_name="John", last_name="Doe", age=22
        )

        test_domain.get_dao(Person).update(person, age=10)
        updated_person = test_domain.get_dao(Person).get(identifier)
        assert updated_person is not None
        assert updated_person.age == 10

    def test_that_updating_a_deleted_aggregate_raises_object_not_found_error(
        self, test_domain
    ):
        """Try to update a non-existing entry"""

        person = test_domain.get_dao(Person).create(
            first_name="Johnny", last_name="John"
        )
        test_domain.get_dao(Person).delete(person)
        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).update(person, {"age": 10})

    def test_updating_record_with_dictionary_args(self, test_domain):
        """ Update an existing entity in the repository"""
        identifier = uuid4()
        person = test_domain.get_dao(Person).create(
            id=identifier, first_name="Johnny", last_name="John", age=2
        )

        test_domain.get_dao(Person).update(person, {"age": 10})
        u_person = test_domain.get_dao(Person).get(identifier)
        assert u_person is not None
        assert u_person.age == 10

    def test_updating_record_with_kwargs(self, test_domain):
        """ Update an existing entity in the repository"""
        identifier = uuid4()
        person = test_domain.get_dao(Person).create(
            id=identifier, first_name="Johnny", last_name="John", age=2
        )

        test_domain.get_dao(Person).update(person, age=10)
        u_person = test_domain.get_dao(Person).get(identifier)
        assert u_person is not None
        assert u_person.age == 10

    def test_updating_record_with_both_dictionary_args_and_kwargs(self, test_domain):
        """ Update an existing entity in the repository"""
        identifier = uuid4()
        person = test_domain.get_dao(Person).create(
            id=identifier, first_name="Johnny", last_name="John", age=2
        )

        test_domain.get_dao(Person).update(person, {"first_name": "Stephen"}, age=10)
        u_person = test_domain.get_dao(Person).get(identifier)
        assert u_person is not None
        assert u_person.age == 10
        assert u_person.first_name == "Stephen"

    def test_updating_record_through_filter(self, test_domain):
        """Test that update by query updates only correct records"""
        identifier1 = uuid4()
        identifier2 = uuid4()
        identifier3 = uuid4()
        identifier4 = uuid4()
        test_domain.get_dao(Person).create(
            id=identifier1, first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.get_dao(Person).create(
            id=identifier2, first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.get_dao(Person).create(
            id=identifier3, first_name="Aramis", last_name="Musketeer", age=4
        )
        test_domain.get_dao(Person).create(
            id=identifier4, first_name="dArtagnan", last_name="Musketeer", age=5
        )

        # Perform update
        updated_count = (
            test_domain.get_dao(Person)
            .query.filter(age__gt=3)
            .update(last_name="Fraud")
        )

        # Query and check if only the relevant records have been updated
        assert updated_count == 2

        u_person1 = test_domain.get_dao(Person).get(identifier1)
        u_person2 = test_domain.get_dao(Person).get(identifier2)
        u_person3 = test_domain.get_dao(Person).get(identifier3)
        u_person4 = test_domain.get_dao(Person).get(identifier4)
        assert u_person1.last_name == "Musketeer"
        assert u_person2.last_name == "Musketeer"
        assert u_person3.last_name == "Fraud"
        assert u_person4.last_name == "Fraud"

    def test_updating_multiple_records_through_filter_with_arg_value(self, test_domain):
        """Try updating all records satisfying filter in one step, passing a dict"""
        identifier1 = uuid4()
        identifier2 = uuid4()
        identifier3 = uuid4()
        identifier4 = uuid4()
        test_domain.get_dao(Person).create(
            id=identifier1, first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.get_dao(Person).create(
            id=identifier2, first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.get_dao(Person).create(
            id=identifier3, first_name="Aramis", last_name="Musketeer", age=4
        )
        test_domain.get_dao(Person).create(
            id=identifier4, first_name="dArtagnan", last_name="Musketeer", age=5
        )

        # Perform update
        updated_count = (
            test_domain.get_dao(Person)
            .query.filter(age__gt=3)
            .update_all({"last_name": "Fraud"})
        )

        # Query and check if only the relevant records have been updated
        assert updated_count == 2

        u_person1 = test_domain.get_dao(Person).get(identifier1)
        u_person2 = test_domain.get_dao(Person).get(identifier2)
        u_person3 = test_domain.get_dao(Person).get(identifier3)
        u_person4 = test_domain.get_dao(Person).get(identifier4)
        assert u_person1.last_name == "Musketeer"
        assert u_person2.last_name == "Musketeer"
        assert u_person3.last_name == "Fraud"
        assert u_person4.last_name == "Fraud"

    def test_updating_multiple_records_through_filter_with_kwarg_value(
        self, test_domain
    ):
        """Try updating all records satisfying filter in one step"""
        identifier1 = uuid4()
        identifier2 = uuid4()
        identifier3 = uuid4()
        identifier4 = uuid4()
        test_domain.get_dao(Person).create(
            id=identifier1, first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.get_dao(Person).create(
            id=identifier2, first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.get_dao(Person).create(
            id=identifier3, first_name="Aramis", last_name="Musketeer", age=4
        )
        test_domain.get_dao(Person).create(
            id=identifier4, first_name="dArtagnan", last_name="Musketeer", age=5
        )

        # Perform update
        updated_count = (
            test_domain.get_dao(Person)
            .query.filter(age__gt=3)
            .update_all(last_name="Fraud")
        )

        # Query and check if only the relevant records have been updated
        assert updated_count == 2

        u_person1 = test_domain.get_dao(Person).get(identifier1)
        u_person2 = test_domain.get_dao(Person).get(identifier2)
        u_person3 = test_domain.get_dao(Person).get(identifier3)
        u_person4 = test_domain.get_dao(Person).get(identifier4)
        assert u_person1.last_name == "Musketeer"
        assert u_person2.last_name == "Musketeer"
        assert u_person3.last_name == "Fraud"
        assert u_person4.last_name == "Fraud"


@pytest.mark.postgresql
class TestDAOValidations:
    """This class holds tests for DAO class"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(User)

    def test_unique(self, test_domain):
        """ Test the unique constraints for the entity """
        test_domain.get_dao(User).create(email="john.doe@gmail.com", password="a1b2c3")

        with pytest.raises(ValidationError) as err:
            test_domain.get_dao(User).create(
                email="john.doe@gmail.com", password="d4e5r6"
            )
        assert err.value.messages == {
            "email": ["User with email 'john.doe@gmail.com' is already present."]
        }

    def test_that_field_required_validations_are_triggered_on_incorrect_attribute_setting(
        self,
    ):
        """Test failed `save()` because of validation errors"""
        person = Person(first_name="Johnny", last_name="John")

        with pytest.raises(ValidationError) as error:
            person.first_name = ""  # Simulate an error by force-resetting an attribute

        assert error.value.messages == {"first_name": ["is required"]}

    def test_that_primitive_validations_on_type_are_thrown_correctly_on_initialization(
        self, test_domain
    ):
        with pytest.raises(ValidationError) as error:
            Person(first_name="Johnny", last_name="John", age="x")

        assert error.value.messages == {"age": ['"x" value must be an integer.']}

    def test_that_primitive_validations_on_type_are_thrown_correctly_on_update(
        self, test_domain
    ):
        person = test_domain.get_dao(Person).create(
            first_name="John", last_name="Doe", age=22
        )

        with pytest.raises(ValidationError) as error:
            test_domain.get_dao(Person).update(
                person, age="x"
            )  # Age should be an integer

        assert error.value.messages == {"age": ['"x" value must be an integer.']}


@pytest.mark.postgresql
class TestDAOLookup:
    """This class holds tests for Lookup Class"""

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
