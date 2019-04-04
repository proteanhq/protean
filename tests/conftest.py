"""Module to setup Factories and other required artifacts for tests"""
import os

import pytest

os.environ['PROTEAN_CONFIG'] = 'tests.support.sample_config'


@pytest.fixture(scope="session", autouse=True)
def register_models():
    """Register Test Models with Dict Repo

       Run only once for the entire test suite
    """
    from protean.core.repository import repo_factory
    from tests.support.dog import (DogModel, RelatedDogModel, DogRelatedByEmailModel,
                                   HasOneDog1Model, HasOneDog2Model, HasOneDog3Model,
                                   HasManyDog1Model, HasManyDog2Model, HasManyDog3Model,
                                   ThreadedDogModel)
    from tests.support.human import (HumanModel, HasOneHuman1Model,
                                     HasOneHuman2Model, HasOneHuman3Model,
                                     HasManyHuman1Model, HasManyHuman2Model,
                                     HasManyHuman3Model)

    repo_factory.register(DogModel)
    repo_factory.register(RelatedDogModel)
    repo_factory.register(DogRelatedByEmailModel)
    repo_factory.register(HasOneDog1Model)
    repo_factory.register(HasOneDog2Model)
    repo_factory.register(HasOneDog3Model)
    repo_factory.register(HasManyDog1Model)
    repo_factory.register(HasManyDog2Model)
    repo_factory.register(HasManyDog3Model)
    repo_factory.register(HumanModel)
    repo_factory.register(HasOneHuman1Model)
    repo_factory.register(HasOneHuman2Model)
    repo_factory.register(HasOneHuman3Model)
    repo_factory.register(HasManyHuman1Model)
    repo_factory.register(HasManyHuman2Model)
    repo_factory.register(HasManyHuman3Model)
    repo_factory.register(ThreadedDogModel)


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
