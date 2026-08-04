"""A cache TTL that arrives as a string must still be a number of seconds.

`TTL = "${CACHE_TTL|3600}"` is the form the `protean new` scaffold ships, and
environment substitution runs over already-parsed TOML strings, so the value
reaches the adapter as `"3600"` with no type to restore. Neither cache adapter
coped: the Redis one computed `"3600" * 1000`, a 4000-digit expiry, and the
memory one raised `TypeError` on the first write. Both failures happen well away
from the config that caused them, which is why the coercion sits in `BaseCache`.
"""

from __future__ import annotations

import pytest

from protean.adapters.cache.memory import MemoryCache
from protean.exceptions import ConfigurationError
from protean.port.cache import DEFAULT_TTL, _resolve_ttl


class TestTTLCoercion:
    @pytest.mark.parametrize(
        ("configured", "expected"),
        [
            ("3600", 3600),
            (" 3600 ", 3600),
            ("+3600", 3600),
            ("2.5", 2.5),
            (3600, 3600),
            (2.5, 2.5),
        ],
    )
    def test_a_numeric_value_resolves_to_a_number(self, configured, expected):
        resolved = _resolve_ttl(configured, "default")
        assert resolved == expected
        assert isinstance(resolved, (int, float))
        assert not isinstance(resolved, str)

    def test_an_integral_string_stays_an_int(self):
        """`3600.0` seconds is a surprising thing to find in a log line."""
        assert isinstance(_resolve_ttl("3600", "default"), int)

    @pytest.mark.parametrize("configured", [None, ""])
    def test_an_unset_ttl_falls_back_to_the_default(self, configured):
        assert _resolve_ttl(configured, "default") == DEFAULT_TTL


class TestTTLIsRejectedWhenItIsNotSeconds:
    """A wrong TTL should name the cache, not surface later as a `TypeError`."""

    def test_a_non_numeric_string_is_rejected(self):
        with pytest.raises(ConfigurationError) as exc:
            _resolve_ttl("one hour", "sessions")
        assert "sessions" in str(exc.value)
        assert "CACHE_TTL" in str(exc.value)

    def test_an_unresolved_env_var_is_rejected(self):
        """The shape a typo'd variable name leaves behind."""
        with pytest.raises(ConfigurationError):
            _resolve_ttl("${CACHE_TTL}", "default")

    def test_a_boolean_is_rejected_rather_than_read_as_one_second(self):
        with pytest.raises(ConfigurationError) as exc:
            _resolve_ttl(True, "default")
        assert "number of seconds" in str(exc.value)


class TestTheAdaptersUseTheResolvedValue:
    def test_memory_cache_accepts_a_string_ttl(self):
        """Previously `TypeError: unsupported operand type(s) for +`."""
        cache = MemoryCache("default", None, {"provider": "memory", "TTL": "3600"})
        assert cache.ttl == 3600
        cache._db["k"] = {"a": 1}
        assert cache._db["k"] == {"a": 1}

    def test_memory_cache_without_a_ttl_still_works(self):
        cache = MemoryCache("default", None, {"provider": "memory"})
        assert cache.ttl == DEFAULT_TTL

    def test_the_redis_expiry_is_computable_from_a_string_ttl(self):
        """`int(ttl * 1000)` is what `psetex` receives."""
        resolved = _resolve_ttl("3600", "default")
        assert int(resolved * 1000) == 3_600_000
