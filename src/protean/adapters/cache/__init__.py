"""Package for  Concrete Implementations of Protean repositories"""

import collections
import importlib
import logging

from protean.exceptions import ConfigurationError
from protean.utils.inflection import underscore

logger = logging.getLogger(__name__)

CACHE_PROVIDERS = {
    "memory": "protean.adapters.cache.memory.MemoryCache",
    "redis": "protean.adapters.cache.redis.RedisCache",
}


class Caches(collections.abc.MutableMapping):
    def __init__(self, domain):
        self.domain = domain
        self._caches = None

    def __getitem__(self, key):
        return self._caches[key] if self._caches else None

    def __iter__(self):
        return iter(self._caches) if self._caches else iter({})

    def __len__(self):
        return len(self._caches) if self._caches else 0

    def __setitem__(self, key, value):
        if self._caches is None:
            self.caches = {}

        self._caches[key] = value

    def __delitem__(self, key):
        if key in self._caches:
            del self._caches[key]

    def _initialize(self):
        """Read config file and initialize providers"""
        configured_caches = self.domain.config["caches"]
        cache_objects = {}

        if configured_caches and isinstance(configured_caches, dict):
            if "default" not in configured_caches:
                raise ConfigurationError("You must define a 'default' provider")

            for cache_name, conn_info in configured_caches.items():
                provider_full_path = CACHE_PROVIDERS[conn_info["provider"]]
                provider_module, provider_class = provider_full_path.rsplit(
                    ".", maxsplit=1
                )

                cache_cls = getattr(
                    importlib.import_module(provider_module), provider_class
                )
                provider = cache_cls(cache_name, self, conn_info)

                cache_objects[cache_name] = provider

        self._caches = cache_objects

    def get_connection(self, provider_name="default"):
        """Fetch connection from Provider"""
        if self._caches is None:
            self._initialize()

        try:
            return self._caches[provider_name].get_connection()
        except KeyError:
            raise AssertionError(f"No Provider registered with name {provider_name}")

    def cache_for(self, view_cls):
        """Retrieve cache associated with the View"""
        if self._caches is None:
            self._initialize()

        view_provider = view_cls.meta_.provider

        cache = self.get(view_provider)

        view_name = underscore(view_cls.__name__)
        if view_name not in cache._views:
            cache.register_view(view_cls)

        return cache
