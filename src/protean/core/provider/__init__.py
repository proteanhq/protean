""" Provider classes for Database configurations and connections"""
# Standard Library Imports
import importlib

# Protean
from protean.conf import Config, active_config
from protean.core.exceptions import ConfigurationError


class Providers:
    """Application Singleton to configure and manage database connections
    """
    def __init__(self, domain, config_file=None):
        """Read config file and initialize providers"""
        self.domain = domain
        self.config = Config(config_module_str=config_file) if config_file else active_config
        self._providers = self._initialize_providers()

    def _initialize_providers(self):
        """Read config file and initialize providers"""
        configured_providers = self.config.DATABASES
        provider_objects = {}

        if configured_providers and isinstance(configured_providers, dict):
            if 'default' not in configured_providers:
                raise ConfigurationError(
                    "You must define a 'default' provider")

            for provider_name, conn_info in configured_providers.items():
                provider_full_path = conn_info['PROVIDER']
                provider_module, provider_class = provider_full_path.rsplit('.', maxsplit=1)

                provider_cls = getattr(importlib.import_module(provider_module), provider_class)
                provider_objects[provider_name] = provider_cls(self.domain, conn_info)

        return provider_objects

    def get_provider(self, provider_name='default'):
        """Fetch provider with the name specified in Configuration file"""
        try:
            return self._providers[provider_name]
        except KeyError:
            raise AssertionError(f'No Provider registered with name {provider_name}')

    def get_connection(self, provider_name='default'):
        """Fetch connection from Provider"""
        try:
            return self._providers[provider_name].get_connection()
        except KeyError:
            raise AssertionError(f'No Provider registered with name {provider_name}')
