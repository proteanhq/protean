import pytest

from .elements import Person, PersonRepository, User


class TestDAO:
    """This class holds tests for DAO class"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonRepository, part_of=Person)
        test_domain.register(User)

    def test_successful_initialization_of_dao(self, test_domain):
        test_domain.repository_for(Person)._dao.query.all()
        provider = test_domain.providers["default"]
        conn = provider.get_connection()
        assert isinstance(conn._db["data"], dict)

    def test_that_escaped_quotes_in_values_are_handled_properly(self, test_domain):
        test_domain.repository_for(Person)._dao.create(
            id="1", first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.repository_for(Person)._dao.create(
            id="3", first_name="Aramis", last_name="Musketeer", age=4
        )

        person1 = test_domain.repository_for(Person)._dao.create(
            first_name="d'Artagnan1", last_name="John", age=5
        )
        person2 = test_domain.repository_for(Person)._dao.create(
            first_name="d'Artagnan2", last_name="John", age=5
        )
        person3 = test_domain.repository_for(Person)._dao.create(
            first_name='d"Artagnan3', last_name="John", age=5
        )
        person4 = test_domain.repository_for(Person)._dao.create(
            first_name='d"Artagnan4', last_name="John", age=5
        )

        assert all(
            person is not None for person in [person1, person2, person3, person4]
        )
