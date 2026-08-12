import math
from abc import ABCMeta, abstractmethod
from typing import Any

from protean.core.projection import BaseProjection
from protean.exceptions import ConfigurationError
from protean.utils.inflection import underscore

DEFAULT_TTL = 300
"""Seconds a cached projection lives when the cache config sets no `TTL`."""

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

    A TTL arriving here as a string is the normal case, not an edge one:
    `TTL = "${CACHE_TTL|3600}"` substitutes to the string `"3600"`, because
    environment substitution runs over already-parsed TOML strings and has no
    type to restore. Left as a string it does not fail loudly. `ttl * 1000` in the Redis
    cache repeats the string a thousand times and then asks Redis to expire a
    key in a 4000-digit number of milliseconds, and the memory cache raises
    `TypeError: unsupported operand type(s) for +: 'float' and 'str'` on the
    first write.

    The range check matters for the same reason. `float("nan")` parses happily
    and every comparison against it is false, so a NaN TTL makes the memory
    cache hold entries **forever** with nothing raised and nothing logged. NaN
    and infinity then fail at the Redis write instead (`ValueError`,
    `OverflowError`), and a negative TTL reaches Redis as a negative expiry. All
    of them are rejected here, where the message can still name what set them.
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
        `add(projection, ttl=0)` used to fall through to the default, so a
        caller asking for immediate expiry silently got 300 seconds. Zero is now
        rejected by the same rule that rejects it in config, which is at least a
        visible answer.

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
        """Add projection record to cache

        KEY: Projection ID
        Value: Projection Data (derived from `to_dict()`)

        TTL is in seconds. Accepts a number, or a string holding one, because a
        TTL sourced from config arrives as a string: environment substitution
        runs over already-parsed TOML strings. Anything that is not a positive,
        finite number of seconds raises a `ConfigurationError` naming the cache.

        Omitted (or an empty string) means "use this cache's `TTL`", which falls
        back to 300 seconds when the cache configures none.

        Args:
            projection (BaseProjection): Projection Instance containing data
            ttl (int, float, str, optional): Timeout in seconds. Defaults to None.
        """

    @abstractmethod
    def get(self, key: str) -> BaseProjection | None:
        """Retrieve data by key"""

    @abstractmethod
    def get_all(
        self, key_pattern: str, last_position: int = 0, size: int = 25
    ) -> list[BaseProjection]:
        """Retrieve projections whose key matches `key_pattern`, one page at a time.

        `key_pattern` is a glob. `*` matches any run of characters, `?`
        matches one, `[...]` is a character class, and other characters,
        including `.`, are literal. Keys are `name:::identifier`, so a
        projection's entries are `"user_profile:::*"`. Every adapter agrees on
        `*`, `?`, and literal characters; bracket negation and escaping can
        differ between adapters, so keep patterns to the `name:::*` shape.

        Every adapter paginates the same way. The matching entries are ordered
        by key ascending, and within that order:

        - `last_position` is a zero-based offset into it.
        - `size` is the maximum number of entries returned.
        - an offset at or past the end returns an empty list.

        So the same `last_position` names the same entry on every adapter, and a
        caller walks a result set by stepping `last_position` forward by `size`
        each call. On a store with no native ordering (Redis), this scans every
        matching key per call to produce the stable order.
        """

    @abstractmethod
    def count(self, key_pattern: str) -> int:
        """Retrieve count of data by key pattern.

        `key_pattern` is a glob. See `get_all` for the syntax.
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
        """Remove a cache record by key pattern.

        `key_pattern` is a glob. See `get_all` for the syntax.
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

        Seconds, like every other TTL on this port. Stating it is the point:
        without a unit in the contract, the Redis adapter returned `PTTL`
        directly and answered milliseconds while the memory adapter answered
        seconds, and each adapter's own tests agreed with it (#1307).

        Every adapter answers the same three cases:

        - `None` when there is no such key.
        - `math.inf` when the key exists and never expires.
        - the seconds remaining otherwise.
        """
