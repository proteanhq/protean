import pytest

from protean.exceptions import ValidationError

from .elements import Person, PersonRepository


class TestState:
    """Class that holds tests for Entity State Management"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonRepository, aggregate_cls=Person)

    def test_that_a_default_state_is_available_when_the_entity_instantiated(self):
        person = Person(first_name="John", last_name="Doe")
        assert person.state_ is not None
        assert person.state_._new
        assert person.state_.is_new
        assert not person.state_.is_persisted

    def test_that_retrieved_objects_are_not_marked_as_new(self, test_domain):
        person = test_domain.get_dao(Person).create(first_name="John", last_name="Doe")
        db_person = test_domain.get_dao(Person).get(person.id)

        assert not db_person.state_.is_new

    def test_that_entity_is_marked_as_saved_after_successful_persistence(
        self, test_domain
    ):
        person = Person(first_name="John", last_name="Doe")
        assert person.state_.is_new

        test_domain.get_dao(Person).save(person)
        assert person.state_.is_persisted

    def test_that_a_new_entity_still_shows_as_new_if_persistence_failed(
        self, test_domain
    ):
        person = Person(first_name="John", last_name="Doe")
        try:
            del person.first_name
            test_domain.get_dao(Person).save(person)
        except ValidationError:
            assert person.state_.is_new

    def test_that_a_changed_entity_still_shows_as_changed_if_persistence_failed(
        self, test_domain
    ):
        person = test_domain.get_dao(Person).create(first_name="John", last_name="Doe")

        person.first_name = "Jane"
        assert person.state_.is_changed

        try:
            del person.first_name
            test_domain.get_dao(Person).save(person)
        except ValidationError:
            assert person.state_.is_changed

    def test_that_entity_is_marked_as_not_new_after_successful_persistence(
        self, test_domain
    ):
        person = test_domain.get_dao(Person).create(first_name="John", last_name="Doe")
        assert not person.state_.is_new

    def test_that_aggregate_copying_resets_state_in_the_new_aggregate_object(
        self, test_domain
    ):
        person1 = test_domain.get_dao(Person).create(first_name="John", last_name="Doe")
        person2 = person1.clone()

        assert person2.state_.is_new

    def test_that_entity_marked_as_changed_if_attributes_are_updated(self, test_domain):
        person = test_domain.get_dao(Person).create(first_name="John", last_name="Doe")
        assert not person.state_.is_changed

        person.first_name = "Jane"
        assert person.state_.is_changed

    def test_that_entity_is_not_marked_as_changed_upon_attr_change_if_still_new(self):
        person = Person(first_name="John", last_name="Doe")
        assert not person.state_.is_changed

        person.first_name = "Jane Doe"
        assert not person.state_.is_changed

    def test_that_aggregate_is_marked_as_not_changed_after_save(self, test_domain):
        person = test_domain.get_dao(Person).create(first_name="John", last_name="Doe")
        person.first_name = "Jane"
        assert person.state_.is_changed

        test_domain.get_dao(Person).save(person)
        assert not person.state_.is_changed

    def test_that_an_entity_is_marked_as_destroyed_after_delete(self, test_domain):
        person = test_domain.get_dao(Person).create(first_name="John", last_name="Doe")
        assert not person.state_.is_destroyed

        test_domain.get_dao(Person).delete(person)
        assert person.state_.is_destroyed
