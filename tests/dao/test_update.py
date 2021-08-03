import pytest

from protean.exceptions import ObjectNotFoundError

from .elements import Person, PersonRepository, User


class TestDAOUpdateFunctionality:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonRepository, aggregate_cls=Person)
        test_domain.register(User)

    def test_update_an_existing_entity_in_the_repository(self, test_domain):
        person = test_domain.get_dao(Person).create(
            id=11344234, first_name="John", last_name="Doe", age=22
        )

        test_domain.get_dao(Person).update(person, age=10)
        updated_person = test_domain.get_dao(Person).get(11344234)
        assert updated_person is not None
        assert updated_person.age == 10

    def test_that_updating_a_deleted_aggregate_raises_object_not_found_error(
        self, test_domain
    ):
        """Try to update a non-existing entry"""

        person = test_domain.get_dao(Person).create(
            id=11344234, first_name="Johnny", last_name="John"
        )
        test_domain.get_dao(Person).delete(person)
        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).update(person, {"age": 10})

    def test_updating_record_with_dictionary_args(self, test_domain):
        """ Update an existing entity in the repository"""
        person = test_domain.get_dao(Person).create(
            id=2, first_name="Johnny", last_name="John", age=2
        )

        test_domain.get_dao(Person).update(person, {"age": 10})
        u_person = test_domain.get_dao(Person).get(2)
        assert u_person is not None
        assert u_person.age == 10

    def test_updating_record_with_kwargs(self, test_domain):
        """ Update an existing entity in the repository"""
        person = test_domain.get_dao(Person).create(
            id=2, first_name="Johnny", last_name="John", age=2
        )

        test_domain.get_dao(Person).update(person, age=10)
        u_person = test_domain.get_dao(Person).get(2)
        assert u_person is not None
        assert u_person.age == 10

    def test_updating_record_with_both_dictionary_args_and_kwargs(self, test_domain):
        """ Update an existing entity in the repository"""
        person = test_domain.get_dao(Person).create(
            id=2, first_name="Johnny", last_name="John", age=2
        )

        test_domain.get_dao(Person).update(person, {"first_name": "Stephen"}, age=10)
        u_person = test_domain.get_dao(Person).get(2)
        assert u_person is not None
        assert u_person.age == 10
        assert u_person.first_name == "Stephen"

    def test_updating_record_through_filter(self, test_domain):
        """Test that update by query updates only correct records"""
        test_domain.get_dao(Person).create(
            id=1, first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.get_dao(Person).create(
            id=2, first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Aramis", last_name="Musketeer", age=4
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="dArtagnan", last_name="Musketeer", age=5
        )

        # Perform update
        updated_count = (
            test_domain.get_dao(Person)
            .query.filter(age__gt=3)
            .update(last_name="Fraud")
        )

        # Query and check if only the relevant records have been updated
        assert updated_count == 2

        u_person1 = test_domain.get_dao(Person).get(1)
        u_person2 = test_domain.get_dao(Person).get(2)
        u_person3 = test_domain.get_dao(Person).get(3)
        u_person4 = test_domain.get_dao(Person).get(4)
        assert u_person1.last_name == "Musketeer"
        assert u_person2.last_name == "Musketeer"
        assert u_person3.last_name == "Fraud"
        assert u_person4.last_name == "Fraud"

    def test_updating_multiple_records_through_filter_with_arg_value(self, test_domain):
        """Try updating all records satisfying filter in one step, passing a dict"""
        test_domain.get_dao(Person).create(
            id=1, first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.get_dao(Person).create(
            id=2, first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Aramis", last_name="Musketeer", age=4
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="dArtagnan", last_name="Musketeer", age=5
        )

        # Perform update
        updated_count = (
            test_domain.get_dao(Person)
            .query.filter(age__gt=3)
            .update_all({"last_name": "Fraud"})
        )

        # Query and check if only the relevant records have been updated
        assert updated_count == 2

        u_person1 = test_domain.get_dao(Person).get(1)
        u_person2 = test_domain.get_dao(Person).get(2)
        u_person3 = test_domain.get_dao(Person).get(3)
        u_person4 = test_domain.get_dao(Person).get(4)
        assert u_person1.last_name == "Musketeer"
        assert u_person2.last_name == "Musketeer"
        assert u_person3.last_name == "Fraud"
        assert u_person4.last_name == "Fraud"

    def test_updating_multiple_records_through_filter_with_kwarg_value(
        self, test_domain
    ):
        """Try updating all records satisfying filter in one step"""
        test_domain.get_dao(Person).create(
            id=1, first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.get_dao(Person).create(
            id=2, first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Aramis", last_name="Musketeer", age=4
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="dArtagnan", last_name="Musketeer", age=5
        )

        # Perform update
        updated_count = (
            test_domain.get_dao(Person)
            .query.filter(age__gt=3)
            .update_all(last_name="Fraud")
        )

        # Query and check if only the relevant records have been updated
        assert updated_count == 2

        u_person1 = test_domain.get_dao(Person).get(1)
        u_person2 = test_domain.get_dao(Person).get(2)
        u_person3 = test_domain.get_dao(Person).get(3)
        u_person4 = test_domain.get_dao(Person).get(4)
        assert u_person1.last_name == "Musketeer"
        assert u_person2.last_name == "Musketeer"
        assert u_person3.last_name == "Fraud"
        assert u_person4.last_name == "Fraud"
