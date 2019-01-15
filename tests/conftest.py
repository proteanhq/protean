"""Module to setup Factories and other required artifacts for tests"""
import os
import pytest

from protean.core.entity import Entity
from protean.core import field

os.environ['PROTEAN_CONFIG'] = 'tests.support.sample_config'


@pytest.fixture(autouse=True)
def run_around_tests():
    """Initialize DogModel with Dict Repo"""
    from protean.impl.repository.dict_repo import DictModel
    from protean.core.repository import repo_factory

    from tests.support.dog import DogModel

    repo_factory.register(DogModel)

    # A test function will be run at this point
    yield

    repo_factory.Dog.delete_all()
