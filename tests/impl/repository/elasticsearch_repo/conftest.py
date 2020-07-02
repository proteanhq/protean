# Standard Library Imports
import os

# Protean
import pytest

from elasticsearch_dsl import Index


def initialize_domain():
    from protean.domain import Domain

    domain = Domain("Elasticsearch Tests")

    # Construct relative path to config file
    current_path = os.path.abspath(os.path.dirname(__file__))
    config_path = os.path.join(current_path, "./config.py")

    if os.path.exists(config_path):
        domain.config.from_pyfile(config_path)

    domain.domain_context().push()
    return domain


@pytest.fixture
def test_domain():
    domain = initialize_domain()

    yield domain


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    test_domain = initialize_domain()

    # Create all indexes
    from .elements import Person, Alien, User, ComplexUser

    test_domain.register(Person)
    test_domain.register(Alien)
    test_domain.register(User)
    test_domain.register(ComplexUser)

    provider = test_domain.get_provider("default")
    conn = provider.get_connection()

    for _, aggregate_record in test_domain.aggregates.items():
        index = Index(aggregate_record.cls.meta_.schema_name, using=conn)
        if not index.exists():
            index.create()

    yield

    # Drop all indexes at the end of test suite
    for _, aggregate_record in test_domain.aggregates.items():
        index = Index(aggregate_record.cls.meta_.schema_name, using=conn)
        if index.exists():
            index.delete()


@pytest.fixture(autouse=True)
def run_around_tests(test_domain):
    yield
    if test_domain.has_provider("default"):
        test_domain.get_provider("default")._data_reset()
