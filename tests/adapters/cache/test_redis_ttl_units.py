"""`get_ttl` answers seconds, and translates Redis' sentinels.

`PTTL` is milliseconds, so #1307 divides by 1000 to match the memory cache and
the rest of the port. Two of its answers are not durations though: `-1` means
the key exists with no expiry, `-2` that there is no such key. Scaling those
would turn documented flags into `-0.001` and `-0.002`, which read as "expiring
imminently" to anything comparing against zero. #1392 unifies the contract
instead: `-1` becomes `math.inf` and `-2` becomes `None`.

Driven through a stub client rather than a live Redis, so it runs in the core
suite: the arithmetic is the whole behaviour under test.
"""

from __future__ import annotations

import math

import pytest

from protean.adapters.cache.redis import RedisCache

pytestmark = pytest.mark.no_test_domain


class _StubClient:
    def __init__(self, answer: int) -> None:
        self._answer = answer

    def pttl(self, key: str) -> int:
        return self._answer


@pytest.fixture
def cache_with(monkeypatch):
    """`_client` is a property, so the stub goes on the class."""

    def _build(pttl_answer: int) -> RedisCache:
        monkeypatch.setattr(
            RedisCache,
            "_client",
            property(lambda self: _StubClient(pttl_answer)),
        )
        return RedisCache.__new__(RedisCache)

    return _build


class TestGetTTLUnits:
    @pytest.mark.parametrize(
        ("milliseconds", "expected_seconds"),
        [(45_000, 45.0), (300_000, 300.0), (1_500, 1.5), (0, 0.0)],
    )
    def test_a_duration_is_converted_to_seconds(
        self, cache_with, milliseconds, expected_seconds
    ):
        assert cache_with(milliseconds).get_ttl("k") == pytest.approx(expected_seconds)


class TestRedisSentinelsAreTranslated:
    """`-1` and `-2` are flags, not durations, so they are not scaled."""

    def test_no_expiry_sentinel_becomes_math_inf(self, cache_with):
        assert cache_with(-1).get_ttl("k") == math.inf

    def test_absent_key_sentinel_becomes_none(self, cache_with):
        assert cache_with(-2).get_ttl("k") is None

    def test_a_sentinel_is_not_mistaken_for_an_imminent_expiry(self, cache_with):
        """Dividing would give -0.001 and -0.002, which any `ttl < 1` misreads."""
        assert cache_with(-1).get_ttl("k") == math.inf
        assert cache_with(-2).get_ttl("k") is None

    def test_an_unexpected_negative_raises(self, cache_with):
        """Redis answers only -2, -1, or a duration. Any other negative is a
        broken client, so it fails loud instead of scaling to a near-zero TTL."""
        with pytest.raises(ValueError, match="Unexpected PTTL value"):
            cache_with(-3).get_ttl("k")
