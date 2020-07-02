# Standard Library Imports
import os

# Protean
import pytest


def initialize_domain():
    from protean.domain import Domain

    domain = Domain("SQLAlchemy Test - SQLite")

    # Construct relative path to config file
    current_path = os.path.abspath(os.path.dirname(__file__))
    config_path = os.path.join(current_path, "./config.py")

    if os.path.exists(config_path):
        domain.config.from_pyfile(config_path)

    return domain


@pytest.fixture(autouse=True)
def test_domain():
    domain = initialize_domain()

    with domain.domain_context():
        yield domain


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    test_domain = initialize_domain()
    # Create all associated tables
    from .elements import Person, Alien, User, ComplexUser

    test_domain.register(Person)
    test_domain.register(Alien)
    test_domain.register(User)
    test_domain.register(ComplexUser)

    test_domain.get_dao(Person)
    test_domain.get_dao(Alien)
    test_domain.get_dao(User)
    test_domain.get_dao(ComplexUser)

    for provider in test_domain.providers_list():
        provider._metadata.create_all()

    yield

    # Drop all tables at the end of test suite
    for provider in test_domain.providers_list():
        provider._metadata.drop_all()


@pytest.fixture(autouse=True)
def run_around_tests(test_domain):
    yield
    if test_domain.has_provider("default"):
        test_domain.get_provider("default")._data_reset()
