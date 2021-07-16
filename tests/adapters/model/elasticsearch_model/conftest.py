import os

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

    return domain


@pytest.fixture
def test_domain():
    domain = initialize_domain()
    with domain.domain_context():
        yield domain


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    domain = initialize_domain()
    with domain.domain_context():
        # Create all indexes
        from .elements import Alien, ComplexUser, Person, Provider, User

        domain.register(Person)
        domain.register(Alien)
        domain.register(User)
        domain.register(ComplexUser)
        domain.register(Provider)

        provider = domain.get_provider("default")
        conn = provider.get_connection()

        for _, aggregate_record in domain.registry.aggregates.items():
            index = Index(aggregate_record.cls.meta_.schema_name, using=conn)
            if not index.exists():
                index.create()

        yield

        # Drop all indexes at the end of test suite
        for _, aggregate_record in domain.registry.aggregates.items():
            index = Index(aggregate_record.cls.meta_.schema_name, using=conn)
            if index.exists():
                index.delete()


@pytest.fixture(autouse=True)
def run_around_tests(test_domain):
    yield
    if test_domain.providers.has_provider("default"):
        test_domain.get_provider("default")._data_reset()
