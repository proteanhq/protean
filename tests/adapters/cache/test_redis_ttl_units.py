"""`get_ttl` answers seconds, and passes Redis' sentinels through unscaled.

`PTTL` is milliseconds, so #1307 divides by 1000 to match the memory cache and
the rest of the port. Two of its answers are not durations though: `-1` means
the key exists with no expiry, `-2` that there is no such key. Scaling those
turns documented flags into `-0.001` and `-0.002`, which read as "expiring
imminently" to anything comparing against zero.

Driven through a stub client rather than a live Redis, so it runs in the core
suite: the arithmetic is the whole behaviour under test.
"""

from __future__ import annotations

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


class TestRedisSentinelsSurvive:
    """`-1` and `-2` are flags, not durations."""

    @pytest.mark.parametrize("sentinel", [-1, -2])
    def test_a_sentinel_passes_through_unscaled(self, cache_with, sentinel):
        assert cache_with(sentinel).get_ttl("k") == float(sentinel)

    def test_a_sentinel_is_not_mistaken_for_an_imminent_expiry(self, cache_with):
        """Dividing gave -0.001 and -0.002, which any `ttl < 1` check misreads."""
        for sentinel in (-1, -2):
            assert cache_with(sentinel).get_ttl("k") <= -1
