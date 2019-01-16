""" Module defines the handler for managing a cache connection """
from protean.conf import active_config
from protean.core.exceptions import ConfigurationError
from protean.utils.importlib import perform_import


class CacheWrapper:
    """
        Manage the connection to the cache and give
        Proxy access to the Cache object's attributes.
    """

    def __init__(self):
        cache_config = active_config.CACHE
        if not isinstance(cache_config, dict) or cache_config == {}:
            raise ConfigurationError(
                "'CACHES' config must be a dict and at least one "
                "database must be defined")

        # Try to import the cache backend
        provider = cache_config.pop('PROVIDER')
        try:
            provider_cls = perform_import(provider)
        except ImportError as e:
            raise ConfigurationError(
                "Could not find cache provider '%s': %s" % (provider, e))
        self.provider = provider_cls(cache_config)


cache = CacheWrapper()
