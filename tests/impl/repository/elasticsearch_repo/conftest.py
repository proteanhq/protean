# Standard Library Imports
import os

# Protean
import pytest


def initialize_domain():
    from protean.domain import Domain
    domain = Domain('Elasticsearch Tests')

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
    # Create all associated tables

    yield

    # Drop all tables at the end of test suite



@pytest.fixture(autouse=True)
def run_around_tests(test_domain):
    yield
    if test_domain.has_provider('default'):
        test_domain.get_provider('default')._data_reset()
