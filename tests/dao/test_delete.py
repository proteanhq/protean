import pytest

from protean.core.queryset import Q
from protean.exceptions import ObjectNotFoundError

from .elements import Person, PersonRepository, User


class TestDAODeleteFunctionality:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonRepository, aggregate_cls=Person)
        test_domain.register(User)

    def test_delete_an_object_in_repository_by_id(self, test_domain):
        """ Delete an object in the reposoitory by ID"""
        person = test_domain.get_dao(Person).create(
            id=3, first_name="John", last_name="Doe", age=22
        )
        deleted_person = test_domain.get_dao(Person).delete(person)
        assert deleted_person is not None
        assert deleted_person.state_.is_destroyed is True

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).get(3)

    def test_delete_all_records_in_repository(self, test_domain):
        """Delete all objects in a repository"""

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

        person_records = test_domain.get_dao(Person).query.filter(Q())
        assert person_records.total == 4

        test_domain.get_dao(Person).delete_all()

        person_records = test_domain.get_dao(Person).query.filter(Q())
        assert person_records.total == 0

    def test_deleting_a_persisted_entity(self, test_domain):
        """ Delete an object in the reposoitory by ID"""
        person = test_domain.get_dao(Person).create(
            id=3, first_name="Jim", last_name="Carrey"
        )
        deleted_person = test_domain.get_dao(Person).delete(person)
        assert deleted_person is not None
        assert deleted_person.state_.is_destroyed is True

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).get(3)

    def test_deleting_all_entities_of_a_type(self, test_domain):
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

        people = test_domain.get_dao(Person).query.all()
        assert people.total == 4

        test_domain.get_dao(Person).delete_all()

        people = test_domain.get_dao(Person).query.all()
        assert people.total == 0

    def test_deleting_all_records_of_a_type_satisfying_a_filter(self, test_domain):
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
            id=4, first_name="d'Artagnan", last_name="Musketeer", age=5
        )

        # Perform update
        deleted_count = test_domain.get_dao(Person).query.filter(age__gt=3).delete_all()

        # Query and check if only the relevant records have been deleted
        assert deleted_count == 2

        person1 = test_domain.get_dao(Person).get(1)
        person2 = test_domain.get_dao(Person).get(2)

        assert person1 is not None
        assert person2 is not None

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).get(3)

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).get(4)

    def test_deleting_records_satisfying_a_filter(self, test_domain):
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
            id=4, first_name="d'Artagnan", last_name="Musketeer", age=5
        )

        # Perform update
        deleted_count = test_domain.get_dao(Person).query.filter(age__gt=3).delete()

        # Query and check if only the relevant records have been updated
        assert deleted_count == 2
        assert test_domain.get_dao(Person).query.all().total == 2

        assert test_domain.get_dao(Person).get(1) is not None
        assert test_domain.get_dao(Person).get(2) is not None
        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).get(3)

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_dao(Person).get(4)
