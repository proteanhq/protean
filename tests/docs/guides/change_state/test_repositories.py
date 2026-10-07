"""Check what docs/guides/change-state/repositories.md says about repositories.

Each test loads its example fresh, so every test gets its own domain and its
own memory database.
"""

import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def custom():
    """The page's first custom repository, with `find_by_email`."""
    module = load_example("guides/change-state/004.py")
    module.domain.init(traverse=False)
    return module


@pytest.fixture
def named_methods():
    """The repository with `adults`, `find_by_email` and `by_country`."""
    module = load_example("guides/change-state/009.py")
    module.domain.init(traverse=False)
    return module


@pytest.fixture
def reporting():
    """The repository tied to memory databases, for a `reporting` provider."""
    module = load_example("guides/change-state/repositories/001.py")
    module.domain.init(traverse=False)
    return module


def test_get_returns_the_aggregate_that_add_stored(custom):
    with custom.domain.domain_context():
        repo = custom.domain.repository_for(custom.Person)
        person = custom.Person(name="John Doe", email="john.doe@example.com")
        repo.add(person)

        found = repo.get(person.id)

        assert found == person
        assert found.name == "John Doe"
        assert found.email == "john.doe@example.com"


def test_repository_for_returns_the_custom_repository(custom):
    with custom.domain.domain_context():
        repo = custom.domain.repository_for(custom.Person)

        assert isinstance(repo, custom.CustomPersonRepository)


def test_find_by_email_returns_the_matching_person(custom):
    with custom.domain.domain_context():
        repo = custom.domain.repository_for(custom.Person)
        john = custom.Person(name="John Doe", email="john.doe@example.com")
        repo.add(john)
        repo.add(custom.Person(name="Jane Doe", email="jane.doe@example.com"))

        found = repo.find_by_email("john.doe@example.com")

        assert found.id == john.id
        assert found.name == "John Doe"


@pytest.fixture
def people(named_methods):
    """Store two adults in different countries and one child."""
    Person = named_methods.Person
    with named_methods.domain.domain_context():
        repo = named_methods.domain.repository_for(Person)
        repo.add(Person(name="Ann", email="ann@example.com", age=30, country="CA"))
        repo.add(Person(name="Bob", email="bob@example.com", age=40, country="US"))
        repo.add(Person(name="Cal", email="cal@example.com", age=12, country="CA"))
    return named_methods


def test_adults_returns_only_people_aged_18_or_more(people):
    with people.domain.domain_context():
        repo = people.domain.repository_for(people.Person)

        assert isinstance(repo, people.PersonRepository)
        assert sorted(person.name for person in repo.adults()) == ["Ann", "Bob"]


def test_by_country_returns_only_people_in_that_country(people):
    with people.domain.domain_context():
        repo = people.domain.repository_for(people.Person)

        assert sorted(person.name for person in repo.by_country("CA")) == [
            "Ann",
            "Cal",
        ]


def test_named_find_by_email_returns_the_matching_person(people):
    with people.domain.domain_context():
        repo = people.domain.repository_for(people.Person)

        assert repo.find_by_email("bob@example.com").name == "Bob"


def test_reporting_provider_is_configured_as_a_memory_database(reporting):
    databases = reporting.domain.config["databases"]

    assert databases["reporting"] == {"provider": "memory"}
    assert reporting.Person.meta_.provider == "reporting"


def test_repository_for_returns_the_memory_repository(reporting):
    with reporting.domain.domain_context():
        repo = reporting.domain.repository_for(reporting.Person)

        assert isinstance(repo, reporting.PersonReportingRepository)


def test_active_users_summary_returns_only_active_people(reporting):
    with reporting.domain.domain_context():
        repo = reporting.domain.repository_for(reporting.Person)
        repo.add(reporting.Person(name="John Doe"))
        repo.add(reporting.Person(name="Jane Doe", active=False))

        summary = repo.active_users_summary()

        assert [person.name for person in summary] == ["John Doe"]
