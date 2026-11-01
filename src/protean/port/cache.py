import logging
import math
from abc import ABCMeta, abstractmethod
from typing import Any, TypeVar

from protean.core.projection import BaseProjection
from protean.exceptions import ConfigurationError
from protean.utils.inflection import underscore

logger = logging.getLogger(__name__)

_Key = TypeVar("_Key")

DEFAULT_TTL = 300
"""Seconds a cached projection lives when the cache config sets no `TTL`."""

GET_ALL_MAX = 1000
"""The most entries `_get_all` returns before it truncates and warns.

`_get_all` is a bounded utility, not a paged read. This cap keeps a match set
that outgrew the store from materialising in full and hiding that a cache is the
wrong place to enumerate it. Past the cap, `_get_all` returns the first
`GET_ALL_MAX` entries in key order and logs a warning naming the pattern and the
match count. It is a fixed number, not a per-call argument: tuning it would make
it a pagination knob again.
"""

TTLValue = int | float | str
"""What a caller may pass as a TTL.

`str` is in there because it is a shape that genuinely arrives: environment
substitution runs over already-parsed TOML strings, so a TTL sourced from
config is a string by the time anyone can pass it on. Every public entry point
coerces through `_resolve_ttl`, so the annotation says what is accepted rather
than what is stored.
"""


def _reject_ttl(source: str, value: Any, reason: str) -> ConfigurationError:
    return ConfigurationError(
        f"{source} has TTL = {value!r}, which is not {reason}. Set a positive "
        "number of seconds, or an environment variable holding one: "
        'TTL = "${CACHE_TTL|3600}".'
    )


def _ttl_unset(value: Any) -> bool:
    """Whether a caller supplied no TTL at all.

    `""` counts because that is what an unset environment variable looks like
    after substitution, and `os.getenv("CACHE_TTL", "")` is a normal way to
    reach these methods. `0` does not count: it is a value, and a rejected one.
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
    # `bool` is an `int`, and `TTL = true` is a typo rather than one second.
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
    # cache keep entries forever without an error.
    if not math.isfinite(number):
        raise _reject_ttl(source, value, "a finite number of seconds")
    if number <= 0:
        raise _reject_ttl(source, value, "a positive number of seconds")
    return number


class BaseCache(metaclass=ABCMeta):
    def __init__(self, name: str, domain: Any, conn_info: dict[str, Any]) -> None:
        """Initialize Cache with Connection/Adapter details"""
        self.name = name
        self.domain = domain
        self.conn_info = conn_info

        self.ttl = _resolve_ttl(conn_info.get("TTL"), f"Cache '{name}'")

        # Temporary cache of projections
        self._projections: dict[str, type[BaseProjection]] = {}

    def _ttl_for(self, ttl: TTLValue | None) -> int | float:
        """The TTL to use for one write: the caller's, else the cache default.

        "Not supplied" is `None` or the empty string, and nothing else.
        Zero is not "not supplied": `add(projection, ttl=0)` is rejected by the
        same rule that rejects it in config, so a caller asking for immediate
        expiry gets an error instead of the default TTL.

        The empty string is here rather than left to `_resolve_ttl` because the
        two have different ideas of what "unset" falls back to. `_resolve_ttl`
        answers `DEFAULT_TTL`, which is right when a cache is being built and
        there is nothing else to fall back to. On a per-call path the cache
        already has a TTL, and that is what should win: otherwise
        `add(p, ttl=os.getenv("CACHE_TTL", ""))` on a cache configured for an
        hour quietly caches for five minutes.
        """
        if _ttl_unset(ttl):
            return self.ttl
        return _resolve_ttl(ttl, f"Cache '{self.name}'")

    def _explicit_ttl(self, ttl: TTLValue | None) -> int | float | None:
        """The caller's TTL, resolved, or `None` if they did not supply one.

        Separate from `_ttl_for` for adapters that only act when a TTL was
        actually given, and so a bad one is rejected *before* anything is
        written: `add` must not leave an entry behind after raising.
        """
        if _ttl_unset(ttl):
            return None
        return _resolve_ttl(ttl, f"Cache '{self.name}'")

    def _capped(self, keys: list[_Key], key_pattern: str) -> list[_Key]:
        """Cap a sorted key list to `GET_ALL_MAX` for `_get_all`, warning if it did.

        Both adapters sort their matching keys ascending and pass them here
        before reading, so the cap and the warning live in one place. Under the
        cap this is a no-op; over it, return the first `GET_ALL_MAX` keys and log
        a warning naming the pattern and how many matched, so a truncated read is
        never silent.
        """
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

    def register_projection(self, projection_cls: type[BaseProjection]) -> None:
        """Registers a projection object for data serialization and de-serialization"""
        projection_name = underscore(projection_cls.__name__)
        self._projections[projection_name] = projection_cls

    def close(self) -> None:
        """Close the cache and release all connections.

        Subclasses that hold external resources (connection pools, sockets,
        etc.) should override this to perform cleanup.  The default
        implementation is a no-op so that adapters without external
        resources (e.g. the in-memory cache) work without changes.
        """

    @abstractmethod
    def ping(self) -> bool:
        """Healthcheck to verify cache is active and accessible"""

    @abstractmethod
    def get_connection(self) -> object:
        """Get the connection object for the cache"""

    @abstractmethod
    def add(self, projection: BaseProjection, ttl: TTLValue | None = None) -> None:
        """Cache the projection's `to_dict()` data under its key.

        The key is `<projection_name>:::<id>`, where `<projection_name>` is the
        projection class name in snake case.

        Args:
            projection: The projection to cache.
            ttl: Seconds the entry lives, as a number or a string holding one.
                `None` or `""` uses this cache's `TTL`, which is `DEFAULT_TTL`
                when the cache configures none.

        Raises:
            ConfigurationError: `ttl` is not a positive, finite number of
                seconds. The message names the cache, and nothing is cached.
        """

    @abstractmethod
    def get(self, key: str) -> BaseProjection | None:
        """Retrieve data by key"""

    @abstractmethod
    def _get_all(self, key_pattern: str) -> list[BaseProjection]:
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
        """

    @abstractmethod
    def count(self, key_pattern: str) -> int:
        """Number of entries whose key matches `key_pattern`.

        `key_pattern` is a glob. See `_get_all` for the syntax. Like `_get_all`,
        this walks the whole keyspace on a store with no native ordering
        (Redis), so it is O(number of keys) per call.
        """

    @abstractmethod
    def remove(self, projection: BaseProjection) -> None:
        """Remove a cache record by projection object

        Does nothing if no record exists for the projection.
        """

    @abstractmethod
    def remove_by_key(self, key: str) -> None:
        """Remove a cache record by key

        Does nothing if the key is absent.
        """

    @abstractmethod
    def remove_by_key_pattern(self, key_pattern: str) -> None:
        """Remove cache records by key pattern.

        `key_pattern` is a glob. See `_get_all` for the syntax.

        Does nothing if the pattern matches no keys.
        """

    @abstractmethod
    def flush_all(self) -> None:
        """Remove all entries in Cache"""

    @abstractmethod
    def set_ttl(self, key: str, ttl: TTLValue) -> None:
        """Set a TTL explicitly on a key.

        Takes the same shapes as `add`: a number, or a string holding one, and
        rejects anything that is not a positive, finite number of seconds,
        whether or not the key is present.

        Otherwise, does nothing if the key is absent.
        """

    @abstractmethod
    def get_ttl(self, key: str) -> float | None:
        """Seconds remaining before `key` expires.

        Seconds, like every other TTL on this port, in every adapter.

        Every adapter answers the same three cases:

        - `None` when there is no such key.
        - `math.inf` when the key exists and never expires.
        - the seconds remaining otherwise.
        """
