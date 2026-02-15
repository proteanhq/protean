import pytest

from tests.shared import initialize_domain


@pytest.fixture(autouse=True)
def test_domain():
    domain = initialize_domain(
        name="SQLAlchemy SQLite Repository Tests", root_path=__file__
    )

    with domain.domain_context():
        yield domain


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    domain = initialize_domain(
        name="SQLAlchemy SQLite Repository DB Setup", root_path=__file__
    )
    with domain.domain_context():
        # Create all associated tables
        from .elements import Alien, ComplexUser, Person, User

        domain.register(Person)
        domain.register(Alien)
        domain.register(User)
        domain.register(ComplexUser)
        domain.init(traverse=False)

        domain.repository_for(Person)._dao
        domain.repository_for(Alien)._dao
        domain.repository_for(User)._dao
        domain.repository_for(ComplexUser)._dao

        default_provider = domain.providers["default"]
        default_provider._metadata.create_all(default_provider._engine)

        yield

        # Drop all tables and dispose the engine to release connections
        default_provider = domain.providers["default"]
        default_provider._metadata.drop_all(default_provider._engine)
        default_provider.close()
