import pytest

from protean.exceptions import IncorrectUsageError

from .elements import Person


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)


def test_that_aggregate_can_be_persisted_with_repository(test_domain):
    person_repo = test_domain.repository_for(Person)
    person_repo.add(Person(first_name="John", last_name="Doe"))

    assert len(person_repo._dao.query.all()) == 1


def test_that_an_aggregate_can_be_retrieved_with_repository(test_domain):
    person = Person(first_name="John", last_name="Doe")
    test_domain.repository_for(Person).add(person)

    assert test_domain.repository_for(Person).get(person.id) == person


def test_that_all_aggregates_can_be_retrieved_with_repository(test_domain):
    person = Person(first_name="John", last_name="Doe")
    test_domain.repository_for(Person).add(person)

    assert test_domain.repository_for(Person)._dao.query.all().items == [person]


def test_that_incorrectusageerror_is_raised_when_retrieving_nonexistent_aggregate(
    test_domain,
):
    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.repository_for("Invalid")

    assert exc.value.messages == {
        "element": ["Element Invalid is not registered in domain Test"]
    }
