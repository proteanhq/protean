""" Module to test Config functionality """
import os

import pytest

from protean.conf import Config
from protean.core.exceptions import ConfigurationError


def test_config_module():
    """ Test that config module is loaded correctly"""

    # Do not set any config file
    os.environ['PROTEAN_CONFIG'] = ''
    with pytest.raises(ConfigurationError):
        Config()

    # Set the config file and make sure values get loaded
    os.environ['PROTEAN_CONFIG'] = 'tests.support.sample_config'
    config = Config()
    assert config.TESTING  # pylint: disable=E1101
    assert config.SECRET_KEY == 'abcdefghijklmn'  # pylint: disable=E1101
