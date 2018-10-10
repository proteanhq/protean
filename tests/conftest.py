"""Module to setup Factories and other required artifacts for tests"""

import os

import mock
import pytest


os.environ['PROTEAN_CONFIG'] = 'tests.support.sample_config'


@pytest.fixture(scope='module', autouse=True)
@mock.patch.dict(os.environ, {'PROTEAN_CONFIG': 'tests.support.sample_config'})
def config():
    """Global Config fixture for all tests"""

    from protean.conf import active_config
    return active_config
