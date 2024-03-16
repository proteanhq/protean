import pytest

from tests.shared import initialize_domain


@pytest.fixture(autouse=True)
def test_domain():
    domain = initialize_domain(__file__)

    with domain.domain_context():
        yield domain


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    domain = initialize_domain(__file__)
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

        domain.providers["default"]._metadata.create_all()

        yield

        # Drop all tables at the end of test suite
        domain.providers["default"]._metadata.drop_all()
