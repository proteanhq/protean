"""Module to setup Factories and other required artifacts for tests"""
import os

import pytest

os.environ['PROTEAN_CONFIG'] = 'tests.support.sample_config'


@pytest.fixture(autouse=True)
def run_around_tests():
    """Initialize DogModel with Dict Repo"""
    from protean.core.repository import repo_factory

    # A test function will be run at this point
    yield

    repo_factory.Dog.delete_all()
    repo_factory.RelatedDog.delete_all()
    repo_factory.DogRelatedByEmail.delete_all()
    repo_factory.HasOneDog1.delete_all()
    repo_factory.HasOneDog2.delete_all()
    repo_factory.HasOneDog3.delete_all()
    repo_factory.HasManyDog1.delete_all()
    repo_factory.HasManyDog2.delete_all()
    repo_factory.HasManyDog3.delete_all()
    repo_factory.Human.delete_all()
    repo_factory.HasOneHuman1.delete_all()
    repo_factory.HasOneHuman2.delete_all()
    repo_factory.HasOneHuman3.delete_all()
    repo_factory.HasManyHuman1.delete_all()
    repo_factory.HasManyHuman2.delete_all()
    repo_factory.HasManyHuman3.delete_all()
