""" Provider classes for Database configurations and connections"""
import importlib

from protean.conf import active_config
from protean.core.exceptions import ConfigurationError


class Providers:
    """Application Singleton to configure and manage database connections
    """
    def __init__(self):
        self._providers = None

    def _initialize_providers(self):
        """Read config file and initialize providers"""
        configured_providers = active_config.DATABASES
        provider_objects = {}

        if not isinstance(configured_providers, dict) or configured_providers == {}:
            raise ConfigurationError(
                "'DATABASES' config must be a dict and at least one "
                "provider must be defined")

        if 'default' not in configured_providers:
            raise ConfigurationError(
                "You must define a 'default' provider")

        for provider_name, conn_info in configured_providers.items():
            provider_full_path = conn_info['PROVIDER']
            provider_module, provider_class = provider_full_path.rsplit('.', maxsplit=1)

            provider_cls = getattr(importlib.import_module(provider_module), provider_class)
            provider_objects[provider_name] = provider_cls(conn_info)

        return provider_objects

    def get_provider(self, provider_name='default'):
        """Fetch provider with the name specified in Configuration file"""
        try:
            if self._providers is None:
                self._providers = self._initialize_providers()
            return self._providers[provider_name]
        except KeyError:
            raise AssertionError(f'No Provider registered with name {provider_name}')

    def get_connection(self, provider_name='default'):
        """Fetch connection from Provider"""
        try:
            return self._providers[provider_name].get_connection()
        except KeyError:
            raise AssertionError(f'No Provider registered with name {provider_name}')


providers = Providers()
