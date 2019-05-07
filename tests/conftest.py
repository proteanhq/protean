"""Module to setup Factories and other required artifacts for tests

    isort:skip_file
"""
import os
os.environ['PROTEAN_CONFIG'] = 'tests.support.sample_config'  # isort:skip

import pytest
from tests.support.dog import *
from tests.support.human import *
from tests.support.sqlalchemy.dog import *
from tests.support.sqlalchemy.human import *


def pytest_addoption(parser):
    """Additional options for running tests with pytest"""
    parser.addoption(
        "--slow", action="store_true", default=False, help="run slow tests"
    )
    parser.addoption(
        "--pending", action="store_true", default=False, help="show pending tests"
    )


def pytest_collection_modifyitems(config, items):
    """Configure special markers on tests, so as to control execution"""
    run_slow = run_pending = False

    if config.getoption("--slow"):
        # --slow given in cli: do not skip slow tests
        run_slow = True

    if config.getoption("--pending"):
        run_pending = True

    skip_slow = pytest.mark.skip(reason="need --slow option to run")
    skip_pending = pytest.mark.skip(reason="need --pending option to run")

    for item in items:
        if "slow" in item.keywords and run_slow is False:
            item.add_marker(skip_slow)
        if "pending" in item.keywords and run_pending is False:
            item.add_marker(skip_pending)


@pytest.fixture(scope="session", autouse=True)
def test_domain():
    """Test Domain"""
    from protean.domain import Domain
    return Domain("Test")


@pytest.fixture(scope="session", autouse=True)
def register_domain_elements(test_domain):
    """Register Domain Elements with Stub Infrastructure, like:
    * Models with Dict Repo

    Run only once for the entire test suite
    """

    test_domain.register_elements()

    from protean.core.repository import repo_factory
    from protean.core.provider import providers
    from protean.impl.repository.sqlalchemy_repo import SAProvider

    for entity_name in repo_factory._registry:
        repo_factory.get_repository(repo_factory._registry[entity_name].entity_cls)

    # Now, create all associated tables
    for _, provider in providers._providers.items():
        if isinstance(provider, SAProvider):
            provider._metadata.create_all()

    yield

    # Drop all tables at the end of test suite
    for _, provider in providers._providers.items():
        if isinstance(provider, SAProvider):
            provider._metadata.drop_all()


@pytest.fixture(autouse=True)
def run_around_tests(test_domain):
    """Cleanup Database after each test run"""
    # A test function will be run at this point
    yield

    # Reset Test Data
    from protean.core.provider import providers
    providers.get_provider()._data_reset()

    # SqlAlchemy Entities
    from protean.core.repository import repo_factory
    from tests.support.sqlalchemy.dog import (SqlDog, SqlRelatedDog)
    from tests.support.sqlalchemy.human import (SqlHuman, SqlRelatedHuman)

    repo_factory.get_repository(SqlDog).delete_all()
    repo_factory.get_repository(SqlRelatedDog).delete_all()
    repo_factory.get_repository(SqlHuman).delete_all()
    repo_factory.get_repository(SqlRelatedHuman).delete_all()
