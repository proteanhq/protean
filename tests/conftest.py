"""Module to setup Factories and other required artifacts for tests"""
import os

import pytest

os.environ['PROTEAN_CONFIG'] = 'tests.support.sample_config'


def pytest_addoption(parser):
    """Additional options for running tests with pytest"""
    parser.addoption(
        "--slow", action="store_true", default=False, help="run slow tests"
    )


def pytest_collection_modifyitems(config, items):
    """Configure special markers on tests, so as to control execution"""
    if config.getoption("--slow"):
        # --slow given in cli: do not skip slow tests
        return
    skip_slow = pytest.mark.skip(reason="need --slow option to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


@pytest.fixture(scope="session", autouse=True)
def register_models():
    """Register Test Models with Dict Repo

       Run only once for the entire test suite
    """
    from protean.core.repository import repo_factory
    from tests.support.dog import (Dog, RelatedDog, DogRelatedByEmail, HasOneDog1,
                                   HasOneDog2, HasOneDog3, HasManyDog1, HasManyDog2,
                                   HasManyDog3, ThreadedDog)
    from tests.support.human import (Human, HasOneHuman1, HasOneHuman2, HasOneHuman3,
                                     HasManyHuman1, HasManyHuman2, HasManyHuman3)

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


@pytest.fixture(autouse=True)
def run_around_tests():
    """Cleanup Database after each test run"""
    from protean.core.repository import repo_factory
    from tests.support.dog import (Dog, RelatedDog, DogRelatedByEmail, HasOneDog1,
                                   HasOneDog2, HasOneDog3, HasManyDog1, HasManyDog2,
                                   HasManyDog3, ThreadedDog)
    from tests.support.human import (Human, HasOneHuman1, HasOneHuman2, HasOneHuman3,
                                     HasManyHuman1, HasManyHuman2, HasManyHuman3)

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
