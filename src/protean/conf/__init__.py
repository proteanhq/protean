"""
Settings and configuration for Protean.

Read values from the module specified by the PROTEAN_CONFIG environment
variable, and then from protean.conf.global_config; see the global_config.py
for a list of all possible variables.
"""

import importlib
import os

from protean.conf import default_config
from protean.core.exceptions import ImproperlyConfigured

ENVIRONMENT_VARIABLE = "PROTEAN_CONFIG"


class Config:
    """Holder class for Config Variables"""

    def __init__(self, config_module_str=default_config):
        """Read variables in UPPER_CASE from specified config"""

        # Fetch Config module string from environment if defined, otherwise use default config
        config_module_str = os.environ.get(ENVIRONMENT_VARIABLE, None)
        if config_module_str:
            config_module = importlib.import_module(config_module_str)
        else:
            config_module = default_config

        for setting in dir(config_module):
            if setting.isupper():
                setattr(self, setting, getattr(config_module, setting))

        # store the settings module for future use
        self.CONFIG_MODULE = config_module

        if not getattr(self, 'SECRET_KEY', None):
            raise ImproperlyConfigured("The SECRET_KEY setting must not be empty.")

    def __repr__(self):
        """Print along with Config Module name"""
        return '<%(cls)s "%(config_module)s">' % {
            'cls': self.__class__.__name__,
            'config_module': self.CONFIG_MODULE
        }


active_config = Config()
