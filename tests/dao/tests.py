import pytest

from protean.core.exceptions import ValidationError

from .elements import Person, PersonRepository, User


class TestDAO:
    """This class holds tests for DAO class"""

    @pytest.fixture
    def test_domain(self):
        from protean.domain import Domain
        domain = Domain('Test', 'tests.repository.config')

        yield domain

    @pytest.fixture(autouse=True)
    def run_around_tests(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonRepository, aggregate=Person)
        test_domain.register(User)

        yield

        test_domain.get_provider('default')._data_reset()

    def test_successful_initialization_of_dao(self, test_domain):
        test_domain.get_dao(Person).query.all()
        provider = test_domain.get_provider('default')
        current_db = provider.get_connection()
        assert current_db['data'] == {'person': {}}

    def test_that_update_runs_basic_primitive_validations(self, test_domain):
        person = test_domain.get_dao(Person).create(first_name='John', last_name='Doe', age=22)

        with pytest.raises(ValidationError):
            test_domain.get_dao(Person).update(person, age='x')  # Age should be an integer

    def test_unique(self, test_domain):
        """ Test the unique constraints for the entity """
        test_domain.get_dao(User).create(email='john.doe@gmail.com', password='a1b2c3')

        with pytest.raises(ValidationError) as err:
            test_domain.get_dao(User).create(email='john.doe@gmail.com', password='d4e5r6')
        assert err.value.messages == {
            'email': ['`User` with this `email` already exists.']}

    def test_that_field_level_validations_are_triggered_on_incorrect_attribute_setting(self):
        """Test failed `save()` because of validation errors"""
        person = Person(first_name='Johnny', last_name='John')

        with pytest.raises(ValidationError):
            person.first_name = ""  # Simulate an error by force-resetting an attribute

    def test_that_escaped_quotes_in_values_are_handled_properly(self, test_domain):
        test_domain.get_dao(Person).create(id=1, first_name='Athos', last_name='Musketeer', age=2)
        test_domain.get_dao(Person).create(id=2, first_name='Porthos', last_name='Musketeer', age=3)
        test_domain.get_dao(Person).create(id=3, first_name='Aramis', last_name='Musketeer', age=4)

        person1 = test_domain.get_dao(Person).create(first_name="d'Artagnan1", last_name='John', age=5)
        person2 = test_domain.get_dao(Person).create(first_name="d\'Artagnan2", last_name='John', age=5)
        person3 = test_domain.get_dao(Person).create(first_name="d\"Artagnan3", last_name='John', age=5)
        person4 = test_domain.get_dao(Person).create(first_name='d\"Artagnan4', last_name='John', age=5)

        assert all(person is not None for person in [person1, person2, person3, person4])
