"""Check what docs/guides/change-state/repositories.md says about repositories.

Each test loads its example fresh, so every test gets its own domain and its
own memory database.
"""

import pytest

from protean.core.repository import BaseRepository
from protean.exceptions import ObjectNotFoundError, TooManyObjectsError
from protean.utils.query import Q
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
    """Store three adults, one of them just 18, and two children, one just 17."""
    Person = named_methods.Person
    with named_methods.domain.domain_context():
        repo = named_methods.domain.repository_for(Person)
        repo.add(Person(name="Ann", email="ann@example.com", age=30, country="CA"))
        repo.add(Person(name="Bob", email="bob@example.com", age=40, country="US"))
        repo.add(Person(name="Cal", email="cal@example.com", age=12, country="CA"))
        repo.add(Person(name="Dan", email="dan@example.com", age=17, country="US"))
        repo.add(Person(name="Eve", email="eve@example.com", age=18, country="US"))
    return named_methods


def test_adults_returns_only_people_aged_18_or_more(people):
    with people.domain.domain_context():
        repo = people.domain.repository_for(people.Person)

        assert isinstance(repo, people.PersonRepository)
        assert sorted(person.name for person in repo.adults()) == [
            "Ann",
            "Bob",
            "Eve",
        ]


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
        # The repository is tied to memory databases only.
        assert reporting.PersonReportingRepository.meta_.database == "memory"


def test_active_users_summary_returns_only_active_people(reporting):
    with reporting.domain.domain_context():
        repo = reporting.domain.repository_for(reporting.Person)
        repo.add(reporting.Person(name="John Doe"))
        repo.add(reporting.Person(name="Jane Doe", active=False))

        summary = repo.active_users_summary()

        assert [person.name for person in summary] == ["John Doe"]


@pytest.fixture
def default_repository():
    """The aggregate with no custom repository."""
    module = load_example("guides/change-state/repositories/002.py")
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        yield module


def test_an_aggregate_without_a_custom_repository_gets_the_default(
    default_repository,
):
    repo = default_repository.domain.repository_for(default_repository.Person)

    assert isinstance(repo, BaseRepository)
    assert type(repo).__name__ == "PersonRepository"
    assert type(repo).__module__ == "protean.adapters.repository"


def test_the_default_repository_gets_what_add_stored(default_repository):
    Person = default_repository.Person
    repo = default_repository.domain.repository_for(Person)
    person = Person(name="John Doe", email="john.doe@example.com")
    repo.add(person)

    assert repo.get(person.id) == person
    assert repo.get_or_none("nonexistent-id") is None
    assert repo.find_by(email="john.doe@example.com") == person
    assert repo.exists(Q(email="john.doe@example.com")) is True
    assert repo.find(Q(name="John Doe")).items == [person]


@pytest.fixture
def querying():
    """The repository that queries with `find`, `find_by` and `exists`."""
    module = load_example("guides/change-state/repositories/003.py")
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        repo = module.domain.repository_for(module.Person)
        repo.add(
            module.Person(
                id="ann", name="Ann", email="ann@example.com", age=30, country="CA"
            )
        )
        repo.add(module.Person(name="Bob", email="bob@example.com", age=40))
        repo.add(module.Person(name="Cal", email="cal@example.com", country="CA"))
        repo.add(
            module.Person(name="Dee", email="cal@example.com", age=12, country="CA")
        )
        repo.add(
            module.Person(name="Fay", email="fay@example.com", age=17, country="CA")
        )
        yield module


def repository(module):
    return module.domain.repository_for(module.Person)


def test_adults_in_country_returns_adults_in_that_country_only(querying):
    adults = repository(querying).adults_in_country("CA")

    assert sorted(person.name for person in adults) == ["Ann", "Cal"]


def test_custom_find_by_email_returns_the_matching_person(querying):
    assert repository(querying).find_by_email("bob@example.com").name == "Bob"


def test_has_adults_is_true_only_when_an_adult_is_stored(querying):
    assert repository(querying).has_adults() is True

    minors = load_example("guides/change-state/repositories/003.py")
    minors.domain.init(traverse=False)
    with minors.domain.domain_context():
        assert repository(minors).has_adults() is False

        repository(minors).add(
            minors.Person(name="Gus", email="gus@example.com", age=17)
        )
        assert repository(minors).has_adults() is False

        repository(minors).add(
            minors.Person(name="Hal", email="hal@example.com", age=18)
        )
        assert repository(minors).has_adults() is True


def test_get_raises_object_not_found_for_an_unknown_id(querying):
    with pytest.raises(ObjectNotFoundError):
        repository(querying).get("nonexistent-id")

    assert querying.get_person("nonexistent-id") is None
    assert querying.get_person("ann").name == "Ann"


def test_find_by_raises_object_not_found_when_nothing_matches(querying):
    with pytest.raises(ObjectNotFoundError):
        repository(querying).find_by(email="unknown@example.com")

    assert querying.find_person("unknown@example.com") is None
    assert querying.find_person("ann@example.com").name == "Ann"


def test_find_by_raises_too_many_objects_when_several_match(querying):
    with pytest.raises(TooManyObjectsError):
        repository(querying).find_by(email="cal@example.com")

    with pytest.raises(ValueError, match="More than one person uses cal@example"):
        querying.find_person("cal@example.com")


def test_exists_is_true_or_false_and_never_raises(querying):
    assert repository(querying).exists(Q(email="ann@example.com")) is True
    assert repository(querying).exists(Q(email="john@example.com")) is False

    querying.check_email_is_free("john@example.com")
    with pytest.raises(ValueError, match="Email already taken"):
        querying.check_email_is_free("ann@example.com")


def test_get_or_none_returns_none_for_an_unknown_id(querying):
    assert repository(querying).get_or_none("nonexistent-id") is None

    assert querying.referrer_name("nonexistent-id") == "nobody"
    assert querying.referrer_name("ann") == "Ann"


@pytest.fixture
def entry_point():
    """The example that adds, gets, then deletes through the DAO on import."""
    module = load_example("guides/change-state/repositories/004.py")
    with module.domain.domain_context():
        yield module


def test_repository_for_adds_and_gets_the_person(entry_point):
    assert entry_point.person.id == "42"
    assert entry_point.person.name == "John Doe"
    # get() hands back the stored record, not a new object
    assert entry_point.person.state_.is_persisted
    assert isinstance(entry_point.repo, BaseRepository)


def test_dao_delete_removes_the_stored_record(entry_point):
    repo = entry_point.domain.repository_for(entry_point.Person)

    assert repo.get_or_none("42") is None
    assert repo.query.all().total == 0
