""" Module to test Config functionality """
import os

from protean.conf import Config


def test_default_config_module():
    """ Test that default config module is loaded correctly"""
    # Do not set any config file
    os.environ['PROTEAN_CONFIG'] = ''
    config1 = Config()

    # Config should have considered protean.conf.default_config s default config
    assert config1.SECRET_KEY == 'wR5yJVF!PVA3&bBaFK%e3#MQna%DJfyT'


def test_config_module_load():
    """ Test that specified config module is loaded correctly"""

    # Set the config file and make sure values get loaded
    os.environ['PROTEAN_CONFIG'] = 'tests.support.sample_config'
    config2 = Config()
    assert config2.TESTING
    assert config2.SECRET_KEY == 'abcdefghijklmn'
