"""Module to setup Factories and other required artifacts for tests"""

import pytest
from tests.test_entity import DogFactory  # pylint: disable=W0611


@pytest.fixture(scope='module', autouse=True)
def config():
    """Global Config fixture for all tests"""

    from protean.config import TestConfig
    return TestConfig()
