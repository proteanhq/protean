"""Module to setup Factories and other required artifacts for tests"""
import os

import pytest

os.environ['PROTEAN_CONFIG'] = 'tests.support.sample_config'


@pytest.fixture(autouse=True)
def run_around_tests():
    """Initialize DogModel with Dict Repo"""
    from protean.core.repository import repo_factory
    from tests.support.dog import DogModel, RelatedDogModel
    from tests.support.human import HumanModel

    repo_factory.register(DogModel)
    repo_factory.register(RelatedDogModel)
    repo_factory.register(HumanModel)

    # A test function will be run at this point
    yield

    repo_factory.Dog.delete_all()
    repo_factory.RelatedDog.delete_all()
    repo_factory.Human.delete_all()
