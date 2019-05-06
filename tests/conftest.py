"""Module to setup Factories and other required artifacts for tests"""
import os

import pytest

os.environ['PROTEAN_CONFIG'] = 'tests.support.sample_config'


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
def register_models():
    """Register Test Models with Dict Repo

       Run only once for the entire test suite
    """
    from protean.core.repository import repo_factory
    from protean.core.provider import providers
    from protean.impl.repository.sqlalchemy_repo import SAProvider

    from tests.support.dog import (Dog, RelatedDog, DogRelatedByEmail, HasOneDog1,
                                   HasOneDog2, HasOneDog3, HasManyDog1, HasManyDog2,
                                   HasManyDog3, ThreadedDog, SubDog)
    from tests.support.human import (Human, HasOneHuman1, HasOneHuman2, HasOneHuman3,
                                     HasManyHuman1, HasManyHuman2, HasManyHuman3)
    from tests.support.sqlalchemy.dog import (SqlDog, SqlRelatedDog)
    from tests.support.sqlalchemy.human import (SqlHuman, SqlRelatedHuman)

    repo_factory.register(Dog)
    repo_factory.register(RelatedDog)
    repo_factory.register(DogRelatedByEmail)
    repo_factory.register(HasOneDog1)
    repo_factory.register(HasOneDog2)
    repo_factory.register(HasOneDog3)
    repo_factory.register(HasManyDog1)
    repo_factory.register(HasManyDog2)
    repo_factory.register(HasManyDog3)
    repo_factory.register(Human)
    repo_factory.register(HasOneHuman1)
    repo_factory.register(HasOneHuman2)
    repo_factory.register(HasOneHuman3)
    repo_factory.register(HasManyHuman1)
    repo_factory.register(HasManyHuman2)
    repo_factory.register(HasManyHuman3)
    repo_factory.register(ThreadedDog)
    repo_factory.register(SubDog)

    # SQLAlchemy Models
    repo_factory.register(SqlDog)
    repo_factory.register(SqlRelatedDog)
    repo_factory.register(SqlHuman)
    repo_factory.register(SqlRelatedHuman)

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
def run_around_tests():
    """Cleanup Database after each test run"""
    from protean.core.repository import repo_factory
    from tests.support.dog import (Dog, RelatedDog, DogRelatedByEmail, HasOneDog1,
                                   HasOneDog2, HasOneDog3, HasManyDog1, HasManyDog2,
                                   HasManyDog3, ThreadedDog, SubDog)
    from tests.support.human import (Human, HasOneHuman1, HasOneHuman2, HasOneHuman3,
                                     HasManyHuman1, HasManyHuman2, HasManyHuman3)
    from tests.support.sqlalchemy.dog import (SqlDog, SqlRelatedDog)
    from tests.support.sqlalchemy.human import (SqlHuman, SqlRelatedHuman)

    # A test function will be run at this point
    yield

    repo_factory.get_repository(Dog).delete_all()
    repo_factory.get_repository(RelatedDog).delete_all()
    repo_factory.get_repository(DogRelatedByEmail).delete_all()
    repo_factory.get_repository(HasOneDog1).delete_all()
    repo_factory.get_repository(HasOneDog2).delete_all()
    repo_factory.get_repository(HasOneDog3).delete_all()
    repo_factory.get_repository(HasManyDog1).delete_all()
    repo_factory.get_repository(HasManyDog2).delete_all()
    repo_factory.get_repository(HasManyDog3).delete_all()
    repo_factory.get_repository(Human).delete_all()
    repo_factory.get_repository(HasOneHuman1).delete_all()
    repo_factory.get_repository(HasOneHuman2).delete_all()
    repo_factory.get_repository(HasOneHuman3).delete_all()
    repo_factory.get_repository(HasManyHuman1).delete_all()
    repo_factory.get_repository(HasManyHuman2).delete_all()
    repo_factory.get_repository(HasManyHuman3).delete_all()
    repo_factory.get_repository(ThreadedDog).delete_all()
    repo_factory.get_repository(SubDog).delete_all()

    # SqlAlchemy Entities
    repo_factory.get_repository(SqlDog).delete_all()
    repo_factory.get_repository(SqlRelatedDog).delete_all()
    repo_factory.get_repository(SqlHuman).delete_all()
    repo_factory.get_repository(SqlRelatedHuman).delete_all()
