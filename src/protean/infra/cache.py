"""The `Cache` service and the `Caches` container.

A cache adapter stores dicts under string keys. `Cache` wraps one adapter and
does the projection work on top of it: it builds keys, serializes and rebuilds
projections, resolves TTLs, caps pattern reads, and checks the adapter's
declared capabilities before a gated call.
"""

import logging
import math
from collections.abc import Iterator, MutableMapping
from typing import TYPE_CHECKING, Any, cast

from protean.exceptions import ConfigurationError, NotSupportedError
from protean.infra.registry import caches as cache_registry
from protean.port.cache import (
    CAPABILITY_PORTS,
    CacheCapabilities,
    CachePatternPort,
    CachePort,
    CacheTTLPort,
)
from protean.utils.inflection import underscore
from protean.utils.reflection import id_field

if TYPE_CHECKING:
    from protean.core.projection import BaseProjection
    from protean.domain import Domain

logger = logging.getLogger(__name__)

DEFAULT_TTL = 300
"""Seconds a cached projection lives when the cache config sets no `TTL`."""

GET_ALL_MAX = 1000
"""The most entries `_get_all` returns before it truncates and warns.

`_get_all` reads every match into memory, so it suits tests and small stores.
Past the cap, `_get_all` returns the first `GET_ALL_MAX` entries in key order
and logs a warning naming the pattern and the match count. The warning tells
the caller to page the projection's repository instead. Callers cannot change
the cap per call.
"""

TTLValue = int | float | str
"""What a caller may pass as a TTL.

Environment substitution runs over parsed TOML strings, so a TTL read from
config arrives as a string. Every public entry point converts the value with
`_resolve_ttl`.
"""


def _reject_ttl(source: str, value: Any, reason: str) -> ConfigurationError:
    return ConfigurationError(
        f"{source} has TTL = {value!r}, which is not {reason}. Set a positive "
        "number of seconds, or an environment variable holding one: "
        'TTL = "${CACHE_TTL|3600}".'
    )


def _ttl_unset(value: Any) -> bool:
    """Whether a caller supplied no TTL at all.

    `""` counts because an unset environment variable becomes `""` after
    substitution, and callers pass `os.getenv("CACHE_TTL", "")`. `0` counts as
    a supplied TTL, which `_resolve_ttl` rejects.
    """
    return value is None or value == ""


def _resolve_ttl(value: Any, source: str) -> int | float:
    """Normalise a `TTL` to a positive, finite number of seconds.

    `value` may be a number or a string holding one. `None` or `""` returns
    `DEFAULT_TTL`.

    Raises:
        ConfigurationError: `value` is a boolean, not a number, NaN, infinite,
            zero or negative. The message names `source`.
    """
    if value is None or value == "":
        return DEFAULT_TTL
    # `bool` is a subclass of `int`. `TTL = true` in config is a typo, so it
    # is rejected instead of read as one second.
    if isinstance(value, bool):
        raise _reject_ttl(source, value, "a number of seconds")

    if isinstance(value, (int, float)):
        number: int | float = value
    else:
        try:
            text = str(value).strip()
            number = int(text) if text.lstrip("+-").isdigit() else float(text)
        except (TypeError, ValueError):
            raise _reject_ttl(source, value, "a number of seconds") from None

    # Every comparison with NaN is false, so a NaN TTL would make the memory
    # cache keep entries forever without an error. `math.isfinite` raises
    # `OverflowError` for an int too large to convert to a float.
    try:
        finite = math.isfinite(number)
    except OverflowError:
        finite = False
    if not finite:
        raise _reject_ttl(source, value, "a finite number of seconds")
    if number <= 0:
        raise _reject_ttl(source, value, "a positive number of seconds")
    return number


def _missing_port_members(adapter_cls: type, port: type[object]) -> list[str]:
    """The members `port` adds to `CachePort` that `adapter_cls` lacks."""
    added = sorted(
        getattr(port, "__abstractmethods__", frozenset())
        - CachePort.__abstractmethods__
    )
    return [member for member in added if not hasattr(adapter_cls, member)]


_REQUIRED_ADAPTER_ATTRIBUTES = ("capabilities", "config")


class Cache:
    """The framework's view of one cache adapter.

    `domain.caches[<name>]` and `domain.cache_for(<projection>)` return one.
    Keys have the form `<projection_name>:::<identifier>`, where
    `<projection_name>` is the projection class name in snake case.

    Raises:
        ConfigurationError: When it is built, if the adapter has no
            `capabilities` or `config` attribute, if it declares `TTL` or
            `PATTERN_MATCH` without subclassing `CacheTTLPort` or
            `CachePatternPort`, or if the cache config has a `TTL` that is not
            a positive, finite number of seconds.
    """

    def __init__(self, adapter: CachePort) -> None:
        self._adapter = adapter
        self._check_adapter_attributes()
        self._check_capability_ports()
        self._ttl = _resolve_ttl(adapter.config.get("TTL"), self._source)
        self._projections: dict[str, type[BaseProjection]] = {}

    @property
    def name(self) -> str:
        """The cache's name in the domain config."""
        return self._adapter.name

    @property
    def capabilities(self) -> CacheCapabilities:
        """The behaviours the adapter supports."""
        return self._adapter.capabilities

    @property
    def _source(self) -> str:
        return f"Cache '{self._adapter.name}'"

    def _check_adapter_attributes(self) -> None:
        # An adapter written for the earlier cache base class has neither
        # attribute, and would otherwise fail later with a bare `AttributeError`.
        adapter_cls = type(self._adapter)
        for attribute in _REQUIRED_ADAPTER_ATTRIBUTES:
            if not hasattr(self._adapter, attribute):
                raise ConfigurationError(
                    f"{self._source} uses {adapter_cls.__name__}, which has no "
                    f"`{attribute}` attribute. A cache adapter implements "
                    "`protean.port.cache.CachePort`."
                )

    def _check_capability_ports(self) -> None:
        adapter_cls = type(self._adapter)
        for flag, port in CAPABILITY_PORTS.items():
            if flag in self._adapter.capabilities and port not in adapter_cls.__mro__:
                message = (
                    f"{self._source} declares CacheCapabilities.{flag.name}, but "
                    f"{adapter_cls.__name__} does not subclass {port.__name__}."
                )
                missing = _missing_port_members(adapter_cls, port)
                if missing:
                    message += f" It does not implement: {', '.join(missing)}."
                raise ConfigurationError(message)

    def _require(self, flag: CacheCapabilities) -> None:
        if flag not in self._adapter.capabilities:
            raise NotSupportedError(
                f"{self._source} does not support CacheCapabilities.{flag.name}."
            )

    def _ttl_port(self) -> CacheTTLPort:
        self._require(CacheCapabilities.TTL)
        return cast(CacheTTLPort, self._adapter)

    def _pattern_port(self) -> CachePatternPort:
        self._require(CacheCapabilities.PATTERN_MATCH)
        return cast(CachePatternPort, self._adapter)

    def _key_for(self, projection: "BaseProjection") -> str:
        id_f = id_field(projection)
        assert id_f is not None
        assert id_f.field_name is not None
        identifier = getattr(projection, id_f.field_name)
        return f"{underscore(projection.__class__.__name__)}:::{identifier}"

    def _projection_cls(self, key: str) -> "type[BaseProjection]":
        prefix = key.split(":::")[0]
        if prefix not in self._projections:
            raise KeyError(
                f"No projection is registered in {self._source} under {prefix!r}. "
                "A key or pattern starts with a projection name in snake case, "
                "then `:::`, such as 'user_profile:::*'."
            )
        return self._projections[prefix]

    def _write_ttl(self, ttl: TTLValue | None) -> float | None:
        """The TTL to pass to `put`, or `None` for no expiry.

        A TTL the caller supplied is resolved first, so a bad value raises
        `ConfigurationError` before `NotSupportedError` on a cache without
        `TTL`. An unset TTL falls back to the cache's configured `TTL`, which
        applies only when the adapter declares `TTL`.
        """
        if _ttl_unset(ttl):
            if CacheCapabilities.TTL in self._adapter.capabilities:
                return float(self._ttl)
            return None
        resolved = self._resolved_ttl(ttl)
        self._require(CacheCapabilities.TTL)
        return float(resolved)

    def _resolved_ttl(self, ttl: TTLValue | None) -> int | float:
        """The caller's TTL, resolved, or this cache's `TTL` when it is unset.

        "Unset" is `None` or `""`. An unset TTL takes the cache's configured
        `TTL`, so `add(p, ttl=os.getenv("CACHE_TTL", ""))` on a cache
        configured for an hour caches for an hour. `0` is a supplied TTL, which
        `_resolve_ttl` rejects.
        """
        if _ttl_unset(ttl):
            return self._ttl
        return _resolve_ttl(ttl, self._source)

    def _capped(self, keys: list[str], key_pattern: str) -> list[str]:
        if len(keys) > GET_ALL_MAX:
            logger.warning(
                "cache _get_all(%r) matched %d entries; returning the first %d "
                "in key order. _get_all is a bounded utility, not a paged read: "
                "page large projection sets through the projection's repository.",
                key_pattern,
                len(keys),
                GET_ALL_MAX,
            )
            return keys[:GET_ALL_MAX]
        return keys

    def _register_projection(self, projection_cls: "type[BaseProjection]") -> None:
        """Register a projection class so `get` can rebuild its entries."""
        self._projections[underscore(projection_cls.__name__)] = projection_cls

    def _close(self) -> None:
        """Close the adapter."""
        self._adapter.close()

    def ping(self) -> bool:
        """Whether the cache is reachable."""
        return self._adapter.ping()

    def get_connection(self) -> object:
        """The adapter's native client, such as a `redis.Redis` instance."""
        return self._adapter.get_connection()

    def add(self, projection: "BaseProjection", ttl: TTLValue | None = None) -> None:
        """Cache the projection's `to_dict()` data under its key.

        Args:
            projection: The projection to cache.
            ttl: Seconds the entry lives, as a number or a string holding one.
                `None` or `""` uses this cache's `TTL`, which is `DEFAULT_TTL`
                when the cache configures none. On a cache without
                `CacheCapabilities.TTL`, an unset TTL stores the entry with no
                expiry.

        Raises:
            ConfigurationError: `ttl` is not a positive, finite number of
                seconds. The message names the cache, and nothing is cached.
            NotSupportedError: The caller supplied `ttl` and the cache does not
                support `CacheCapabilities.TTL`. Nothing is cached.
        """
        resolved_ttl = self._write_ttl(ttl)
        self._adapter.put(self._key_for(projection), projection.to_dict(), resolved_ttl)

    def get(self, key: str) -> "BaseProjection | None":
        """The projection cached under `key`, or `None` when there is none.

        Raises:
            KeyError: No projection class is registered under the key's prefix.
        """
        projection_cls = self._projection_cls(key)
        value = self._adapter.get(key)
        return None if value is None else projection_cls(value)

    def _get_all(self, key_pattern: str) -> "list[BaseProjection]":
        """Every projection whose key matches `key_pattern`, in ascending key order.

        It reads every matching entry and may scan the whole keyspace. Use it
        for tests and small stores. To page a large projection set, query the
        projection's repository (`repository_for(Projection).query`).

        `key_pattern` is a glob. `*` matches any run of characters, `?`
        matches one, `[...]` is a character class, and other characters,
        including `.`, are literal. Keys are `name:::identifier`, so a
        projection's entries are `"user_profile:::*"`. Bracket negation and
        escaping can differ between adapters, so keep patterns to the
        `name:::*` shape.

        It returns at most `GET_ALL_MAX` entries. Past that it returns the
        first `GET_ALL_MAX` in key order and logs a warning.

        Raises:
            NotSupportedError: The cache does not support
                `CacheCapabilities.PATTERN_MATCH`.
            KeyError: The text before `:::` in `key_pattern` is not a
                registered projection name. A pattern that starts with a glob,
                such as `"*"`, raises this too.
        """
        port = self._pattern_port()
        projection_cls = self._projection_cls(key_pattern)
        keys = self._capped(port.keys_matching(key_pattern), key_pattern)
        # A key can expire between the scan and this read, so skip a `None`.
        return [
            projection_cls(value)
            for key in keys
            if (value := port.get(key)) is not None
        ]

    def count(self, key_pattern: str) -> int:
        """Number of entries whose key matches `key_pattern`.

        `key_pattern` is a glob. See `_get_all` for the syntax.

        Raises:
            NotSupportedError: The cache does not support
                `CacheCapabilities.PATTERN_MATCH`.
        """
        return self._pattern_port().count_matching(key_pattern)

    def remove(self, projection: "BaseProjection") -> None:
        """Remove the projection's entry. Does nothing if there is none."""
        self._adapter.delete(self._key_for(projection))

    def remove_by_key(self, key: str) -> None:
        """Remove the entry under `key`. Does nothing if the key is absent."""
        self._adapter.delete(key)

    def remove_by_key_pattern(self, key_pattern: str) -> None:
        """Remove every entry whose key matches `key_pattern`.

        `key_pattern` is a glob. See `_get_all` for the syntax. Does nothing if
        the pattern matches no keys.

        Raises:
            NotSupportedError: The cache does not support
                `CacheCapabilities.PATTERN_MATCH`.
        """
        self._pattern_port().delete_matching(key_pattern)

    def clear(self) -> None:
        """Remove every entry in the cache."""
        self._adapter.clear()

    def set_ttl(self, key: str, ttl: TTLValue) -> None:
        """Set a TTL explicitly on a key.

        Takes the same shapes as `add`: a number, or a string holding one.
        `None` or `""` uses this cache's `TTL`. Does nothing if the key is
        absent.

        Raises:
            NotSupportedError: The cache does not support
                `CacheCapabilities.TTL`.
            ConfigurationError: `ttl` is not a positive, finite number of
                seconds, whether or not the key is present.
        """
        port = self._ttl_port()
        port.set_ttl(key, float(self._resolved_ttl(ttl)))

    def get_ttl(self, key: str) -> float | None:
        """Seconds remaining before `key` expires.

        - `None` when there is no such key.
        - `math.inf` when the key exists and never expires.
        - the seconds remaining otherwise.

        Raises:
            NotSupportedError: The cache does not support
                `CacheCapabilities.TTL`.
        """
        return self._ttl_port().get_ttl(key)


class Caches(MutableMapping[str, Cache]):
    """The domain's caches, by name, each a `Cache` around its adapter."""

    def __init__(self, domain: "Domain") -> None:
        self.domain = domain
        self._caches: dict[str, Cache] | None = None

    def __getitem__(self, key: str) -> Cache:
        if not self._caches:
            raise KeyError(key)
        return self._caches[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._caches) if self._caches else iter({})

    def __len__(self) -> int:
        return len(self._caches) if self._caches else 0

    def __setitem__(self, key: str, value: Cache) -> None:
        if self._caches is None:
            self._caches = {}

        self._caches[key] = value

    def __delitem__(self, key: str) -> None:
        if not self._caches:
            raise KeyError(key)
        del self._caches[key]

    def close(self) -> None:
        """Close all cache connections and release resources."""
        if self._caches:
            for name, cache in self._caches.items():
                try:
                    cache._close()
                # One failing cache must not stop closing the rest; logged.
                except Exception:
                    logger.exception("Error closing cache '%s'", name)
            logger.debug("All caches closed")

    def _initialize(self) -> None:
        """Read config file and initialize providers"""
        # Close existing caches before re-initializing to prevent
        # connection leaks (e.g., when domain.init() is called again).
        self.close()

        configured_caches = self.domain.config["caches"]
        cache_objects: dict[str, Cache] = {}

        if configured_caches and isinstance(configured_caches, dict):
            if "default" not in configured_caches:
                raise ConfigurationError("You must define a 'default' provider")

            for cache_name, config in configured_caches.items():
                cache_cls = cache_registry.get(config["provider"])
                adapter = cache_cls(cache_name, self.domain, config)
                cache_objects[cache_name] = Cache(adapter)

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

    def cache_for(self, projection_cls: "type[BaseProjection]") -> Cache:
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
            cache._register_projection(projection_cls)

        return cache
