"""
Settings and configuration for Protean.

Read values from the module specified by the PROTEAN_CONFIG environment
variable, and then from protean.conf.global_config; see the global_config.py
for a list of all possible variables.
"""

import importlib
import os

from protean.conf import default_config
from protean.core.exceptions import ConfigurationError

ENVIRONMENT_VARIABLE = "PROTEAN_CONFIG"


class Config:
    """Holder class for Config Variables"""

    def __init__(self, config_module_str=None):
        """Read variables in UPPER_CASE from specified config

        :param config_module_str: Path of the config module to be loaded
        """

        # Update attrs from default settings
        for setting in dir(default_config):
            if setting.isupper():
                setattr(self, setting, getattr(default_config, setting))

        # Fetch Config module string from environment
        config_module_str = os.environ.get(
            ENVIRONMENT_VARIABLE, config_module_str)

        # If config module is defined then load it and override the attrs
        if config_module_str:
            config_module = importlib.import_module(config_module_str)

            # Override the config attrs
            for setting in dir(config_module):
                if setting.isupper():
                    setattr(self, setting, getattr(config_module, setting))

            # store the settings module for future use
            self.CONFIG_MODULE = config_module
        else:
            self.CONFIG_MODULE = default_config

        if not getattr(self, 'SECRET_KEY', None):
            raise ConfigurationError(
                "The SECRET_KEY setting must not be empty.")

    def __repr__(self):
        """Print along with Config Module name"""
        return '<%(cls)s "%(config_module)s">' % {
            'cls': self.__class__.__name__,
            'config_module': self.CONFIG_MODULE
        }


active_config = Config()
