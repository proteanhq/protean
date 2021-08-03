""" Package for  Concrete Implementations of Protean repositories """
import collections
import importlib
import logging

try:
    collectionsAbc = collections.abc
except AttributeError:
    collectionsAbc = collections

from protean.exceptions import ConfigurationError
from protean.utils.inflection import underscore

logger = logging.getLogger("protean.cache")


class Caches(collectionsAbc.MutableMapping):
    def __init__(self, domain):
        self.domain = domain

        # Caches will be filled dynamically on first call to
        # fetch a repository. This is designed so that the entire
        # domain is loaded before we try to load providers.
        # FIXME Should this be done during domain.init()
        self._caches = None

    def __getitem__(self, key):
        if self._caches is None:
            self._initialize()
        return self._caches[key]

    def __iter__(self):
        if self._caches is None:
            self._initialize()
        return iter(self._caches)

    def __len__(self):
        if self._caches is None:
            self._initialize()
        return len(self._caches)

    def __setitem__(self, key, value):
        if self._caches is None:
            self._initialize()
        self._caches[key] = value

    def __delitem__(self, key):
        if self._caches is None:
            self._initialize()
        del self._caches[key]

    def _initialize(self):
        """Read config file and initialize providers"""
        configured_caches = self.domain.config["CACHES"]
        cache_objects = {}

        if configured_caches and isinstance(configured_caches, dict):
            if "default" not in configured_caches:
                raise ConfigurationError("You must define a 'default' provider")

            for cache_name, conn_info in configured_caches.items():
                provider_full_path = conn_info["PROVIDER"]
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
