# Standard Library Imports
import os

# Protean
import pytest

from tests.old.support.dog import *
from tests.old.support.human import *
from tests.old.support.sqlalchemy.dog import *
from tests.old.support.sqlalchemy.human import *

os.environ['PROTEAN_CONFIG'] = 'tests.old.support.sample_config'  # isort:skip



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

    from protean.core.repository.factory import repo_factory
    from protean.impl.repository.sqlalchemy_repo import SAProvider

    for entity_name in repo_factory._registry:
        repo_factory.get_repository(repo_factory._registry[entity_name].entity_cls)

    # Now, create all associated tables
    for _, provider in test_domain.providers_list.items():
        if isinstance(provider, SAProvider):
            provider._metadata.create_all()

    yield

    # Drop all tables at the end of test suite
    for _, provider in test_domain.providers_list.items():
        if isinstance(provider, SAProvider):
            provider._metadata.drop_all()


@pytest.fixture(autouse=True)
def run_around_tests(test_domain):
    """Cleanup Database after each test run"""
    # A test function will be run at this point
    yield

    # Reset Test Data
    test_domain.get_provider('default')._data_reset()

    # SqlAlchemy Entities
    from protean.core.repository.factory import repo_factory
    from tests.old.support.sqlalchemy.dog import (SqlDog, SqlRelatedDog)
    from tests.old.support.sqlalchemy.human import (SqlHuman, SqlRelatedHuman)

    repo_factory.get_repository(SqlDog)._delete_all()
    repo_factory.get_repository(SqlRelatedDog)._delete_all()
    repo_factory.get_repository(SqlHuman)._delete_all()
    repo_factory.get_repository(SqlRelatedHuman)._delete_all()
