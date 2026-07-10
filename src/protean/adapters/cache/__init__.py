"""Package for  Concrete Implementations of Protean repositories"""

import importlib
import logging
from collections.abc import Iterator, MutableMapping
from typing import TYPE_CHECKING

from protean.exceptions import ConfigurationError
from protean.port.cache import BaseCache
from protean.utils.inflection import underscore

if TYPE_CHECKING:
    from protean.core.projection import BaseProjection
    from protean.domain import Domain

logger = logging.getLogger(__name__)

CACHE_PROVIDERS = {
    "memory": "protean.adapters.cache.memory.MemoryCache",
    "redis": "protean.adapters.cache.redis.RedisCache",
}


class Caches(MutableMapping[str, BaseCache]):
    def __init__(self, domain: "Domain") -> None:
        self.domain = domain
        self._caches: dict[str, BaseCache] | None = None

    def __getitem__(self, key: str) -> BaseCache:
        if not self._caches:
            raise KeyError(key)
        return self._caches[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._caches) if self._caches else iter({})

    def __len__(self) -> int:
        return len(self._caches) if self._caches else 0

    def __setitem__(self, key: str, value: BaseCache) -> None:
        if self._caches is None:
            self._caches = {}

        self._caches[key] = value

    def __delitem__(self, key: str) -> None:
        assert self._caches is not None
        if key in self._caches:
            del self._caches[key]

    def close(self) -> None:
        """Close all cache connections and release resources."""
        if self._caches:
            for name, cache in self._caches.items():
                try:
                    cache.close()
                except Exception:
                    logger.exception("Error closing cache '%s'", name)
            logger.debug("All caches closed")

    def _initialize(self) -> None:
        """Read config file and initialize providers"""
        # Close existing caches before re-initializing to prevent
        # connection leaks (e.g., when domain.init() is called again).
        self.close()

        configured_caches = self.domain.config["caches"]
        cache_objects: dict[str, BaseCache] = {}

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

    def get_connection(self, provider_name: str = "default") -> object:
        """Fetch connection from Provider"""
        if self._caches is None:
            self._initialize()

        try:
            assert self._caches is not None
            return self._caches[provider_name].get_connection()
        except KeyError as exc:
            raise AssertionError(
                f"No Provider registered with name {provider_name}"
            ) from exc

    def cache_for(self, projection_cls: "type[BaseProjection]") -> BaseCache:
        """Retrieve cache associated with the Projection"""
        if self._caches is None:
            self._initialize()

        # Use meta_.cache (the cache adapter name) when the projection is
        # cache-backed.  Fall back to meta_.provider for backward compatibility
        # with projections that call cache_for() without formal registration.
        cache_name = projection_cls.meta_.cache or projection_cls.meta_.provider

        cache = self[cache_name]

        projection_name = underscore(projection_cls.__name__)
        if projection_name not in cache._projections:
            cache.register_projection(projection_cls)

        return cache
