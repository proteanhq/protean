import pytest

from protean.exceptions import ValidationError

from .elements import Person, PersonRepository, User


class TestValidations:
    """This class holds tests for DAO class"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonRepository, aggregate_cls=Person)
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
