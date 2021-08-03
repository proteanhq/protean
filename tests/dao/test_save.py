import pytest

from protean.exceptions import ValidationError

from .elements import Person, PersonRepository, User


class TestDAOSaveFunctionality:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonRepository, aggregate_cls=Person)
        test_domain.register(User)

    def test_creation_throws_error_on_missing_fields(self, test_domain):
        """ Add an entity to the repository missing a required attribute"""
        with pytest.raises(ValidationError) as err:
            test_domain.get_dao(Person).create(last_name="Doe")

        assert err.value.messages == {"first_name": ["is required"]}

    def test_entity_persistence_with_create_method_and_fetch(self, test_domain):
        person = test_domain.get_dao(Person).create(
            id=11344234, first_name="John", last_name="Doe"
        )
        assert person is not None
        assert person.id == 11344234
        assert person.first_name == "John"
        assert person.last_name == "Doe"
        assert person.age == 21

        db_person = test_domain.get_dao(Person).get(11344234)
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
