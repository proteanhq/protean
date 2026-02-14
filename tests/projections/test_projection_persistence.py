import pytest

from protean.core.projection import BaseProjection
from protean.fields import Identifier, Integer, String


class Person(BaseProjection):
    person_id = Identifier(identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.init(traverse=False)


class TestProjectionPersistence:
    def test_projection_can_be_persisted(self, test_domain):
        person = Person(person_id="1", first_name="John", last_name="Doe", age=25)
        test_domain.repository_for(Person).add(person)

        refreshed_person = test_domain.repository_for(Person).get(person.person_id)

        assert refreshed_person.person_id == "1"
        assert refreshed_person.first_name == "John"
        assert refreshed_person.last_name == "Doe"
        assert refreshed_person.age == 25

    def test_projection_can_be_updated(self, test_domain):
        person = Person(person_id="1", first_name="John", last_name="Doe", age=25)
        test_domain.repository_for(Person).add(person)

        person.first_name = "Jane"
        test_domain.repository_for(Person).add(person)

        refreshed_person = test_domain.repository_for(Person).get(person.person_id)

        assert refreshed_person.person_id == "1"
        assert refreshed_person.first_name == "Jane"
        assert refreshed_person.last_name == "Doe"
        assert refreshed_person.age == 25
