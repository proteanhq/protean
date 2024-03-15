import os

import pytest


def initialize_domain():
    from protean.domain import Domain

    domain = Domain(__file__, "SQLAlchemy Test - SQLite")

    # Construct relative path to config file
    current_path = os.path.abspath(os.path.dirname(__file__))
    config_path = os.path.join(current_path, "./config.py")

    if os.path.exists(config_path):
        domain.config.from_pyfile(config_path)

    return domain


@pytest.fixture(autouse=True)
def test_domain():
    domain = initialize_domain()
    domain.reinitialize()

    with domain.domain_context():
        yield domain


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    domain = initialize_domain()
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
