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


class TestTTLMustBePositiveAndFinite:
    """`float()` parses more than numbers, and one of the results is silent.

    `float("nan")` succeeds, and every comparison against NaN is false, so the
    memory cache holds an entry with a NaN TTL **forever** with nothing raised
    and nothing logged. NaN and infinity at least fail at the Redis write
    (`ValueError`, `OverflowError`), but far from the config that caused them,
    and a negative TTL reaches Redis as a negative expiry.
    """

    @pytest.mark.parametrize("configured", ["nan", "NaN", float("nan")])
    def test_nan_is_rejected(self, configured):
        with pytest.raises(ConfigurationError, match="finite"):
            _resolve_ttl(configured, "Cache 'default'")

    @pytest.mark.parametrize(
        "configured", ["inf", "-inf", "Infinity", float("inf"), float("-inf")]
    )
    def test_infinity_is_rejected(self, configured):
        with pytest.raises(ConfigurationError, match="finite"):
            _resolve_ttl(configured, "Cache 'default'")

    @pytest.mark.parametrize("configured", ["-5", -5, "0", 0, -0.5])
    def test_zero_and_negative_are_rejected(self, configured):
        with pytest.raises(ConfigurationError, match="positive"):
            _resolve_ttl(configured, "Cache 'default'")

    def test_the_message_names_the_cache(self):
        with pytest.raises(ConfigurationError) as exc:
            _resolve_ttl("nan", "Cache 'sessions'")
        assert "sessions" in str(exc.value)

    def test_a_nan_ttl_no_longer_reaches_the_memory_cache(self):
        with pytest.raises(ConfigurationError):
            MemoryCache("default", None, {"provider": "memory", "TTL": "nan"})


class TestAPerCallTTL:
    """`ttl or self.ttl` treated an explicit `0` as "not supplied"."""

    def test_an_explicit_ttl_is_used(self):
        cache = MemoryCache("default", None, {"provider": "memory", "TTL": 300})
        assert cache._ttl_for(60) == 60

    def test_omitting_it_falls_back_to_the_cache_default(self):
        cache = MemoryCache("default", None, {"provider": "memory", "TTL": 900})
        assert cache._ttl_for(None) == 900

    def test_a_string_per_call_ttl_is_coerced_like_config(self):
        cache = MemoryCache("default", None, {"provider": "memory"})
        assert cache._ttl_for("60") == 60

    def test_zero_is_rejected_rather_than_silently_becoming_the_default(self):
        """It used to return 300, so "expire immediately" cached for 5 minutes."""
        cache = MemoryCache("default", None, {"provider": "memory", "TTL": 300})
        with pytest.raises(ConfigurationError, match="positive"):
            cache._ttl_for(0)

    def test_an_empty_string_falls_back_to_the_cache_not_the_global_default(self):
        """`ttl=os.getenv("CACHE_TTL", "")` must not shorten a configured TTL.

        `_resolve_ttl("")` answers `DEFAULT_TTL`, which is right when a cache is
        being built and there is nothing else to fall back to. On a per-call
        path the cache already has a TTL, so deferring to `_resolve_ttl` here
        quietly cached for five minutes on a cache configured for an hour.
        """
        cache = MemoryCache("sessions", None, {"provider": "memory", "TTL": 3600})

        assert cache._ttl_for("") == 3600
        assert cache._ttl_for(None) == 3600

    def test_an_empty_string_still_reaches_the_global_default_when_unconfigured(self):
        cache = MemoryCache("plain", None, {"provider": "memory"})

        assert cache._ttl_for("") == DEFAULT_TTL

    def test_a_string_zero_is_still_rejected(self):
        """Only `""` means unset; `"0"` is a value, and a bad one."""
        cache = MemoryCache("sessions", None, {"provider": "memory", "TTL": 3600})
        with pytest.raises(ConfigurationError, match="positive"):
            cache._ttl_for("0")
