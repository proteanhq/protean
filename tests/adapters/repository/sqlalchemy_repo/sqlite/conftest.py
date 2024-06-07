import pytest

from tests.shared import initialize_domain


@pytest.fixture(autouse=True)
def test_domain():
    domain = initialize_domain(__file__, "SQLAlchemy SQLite Repository Tests")

    with domain.domain_context():
        yield domain


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    domain = initialize_domain(__file__, "SQLAlchemy SQLite Repository DB Setup")
    with domain.domain_context():
        # Create all associated tables
        from .elements import Alien, ComplexUser, Person, User

        domain.register(Person)
        domain.register(Alien)
        domain.register(User)
        domain.register(ComplexUser)

        domain.repository_for(Person)._dao
        domain.repository_for(Alien)._dao
        domain.repository_for(User)._dao
        domain.repository_for(ComplexUser)._dao

        default_provider = domain.providers["default"]
        default_provider._metadata.create_all(default_provider._engine)

        yield

        # Drop all tables at the end of test suite
        default_provider = domain.providers["default"]
        default_provider._metadata.drop_all(default_provider._engine)
