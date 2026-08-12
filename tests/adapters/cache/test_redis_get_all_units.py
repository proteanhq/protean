"""`_get_all` reads Redis keys in sorted key order, deduped.

Redis has no native ordering, so `_get_all` collects every matching key with
`scan_iter`, dedupes, sorts them ascending, and materialises them. That sort and
dedupe is the whole behaviour, so it is worth covering on its own.

Driven through a stub client rather than a live Redis, so the logic runs in the
core suite the way `test_redis_ttl_units.py` covers `get_ttl`. The cross-adapter
`TestGetAllReturnsEveryMatchInKeyOrder` in `generic/test_key_patterns.py` still
pins the same contract against a real Redis on the `--redis` leg.
"""

import fnmatch

import pytest

from protean.adapters.cache.redis import RedisCache
from protean.core.projection import BaseProjection
from protean.domain import Domain
from protean.fields import Identifier, String

pytestmark = pytest.mark.no_test_domain


class CacheEntry(BaseProjection):
    key: Identifier(identifier=True)
    value: String(required=True)


class _StubClient:
    """The parts of the Redis client `_get_all`/`add`/`count` touch, backed by a dict.

    Keys and values come back as `bytes`, the way redis-py answers without
    `decode_responses`, so the test exercises the same bytes sort the live
    adapter does. `scan_iter` yields keys in insertion order, deliberately not
    sorted, so a `_get_all` that forgot to sort would return them in the wrong
    order and the order assertion would catch it.
    """

    def __init__(self) -> None:
        self._store: dict[bytes, bytes] = {}

    def ping(self) -> bool:
        return True

    def psetex(self, key: str, ttl_ms: int, value: str) -> None:
        self._store[key.encode()] = value.encode()

    def scan_iter(self, match: str | None = None):
        for key in self._store:  # insertion order, not sorted
            if match is None or fnmatch.fnmatchcase(key.decode(), match):
                yield key

    def get(self, key: bytes) -> bytes | None:
        return self._store.get(key)


def _install(monkeypatch, stub):
    """Point `RedisCache._client` at `stub` and build a domain around it."""
    monkeypatch.setattr(RedisCache, "_client", property(lambda self: stub))

    domain = Domain(name="Test")
    domain.config["caches"]["default"] = {
        "provider": "redis",
        "URI": "redis://localhost:6379/6",
        "TTL": 300,
    }
    domain.register(CacheEntry)
    domain.init(traverse=False)
    return domain


@pytest.fixture
def cache(monkeypatch):
    """A Redis cache whose client is a dict, so it runs without a server."""
    domain = _install(monkeypatch, _StubClient())
    with domain.domain_context():
        yield domain.cache_for(CacheEntry)


PATTERN = "cache_entry:::*"
COUNT = 20
# As strings/bytes, `k10` sorts before `k2`, so the order is not the k0..k19
# insertion order the stub yields; that is what makes the sort observable.
EXPECTED_ORDER = sorted(f"k{i}" for i in range(COUNT))


def _load(cache):
    for i in range(COUNT):
        cache.add(CacheEntry(key=f"k{i}", value=str(i)))


def test_get_all_returns_every_match_in_key_order(cache):
    _load(cache)

    results = cache._get_all(PATTERN)

    assert [entry.key for entry in results] == EXPECTED_ORDER


class _DuplicatingStub(_StubClient):
    """A stub whose `scan_iter` yields the first matching key twice.

    Redis `SCAN` is documented to return the same element more than once during
    a full iteration (rehashing, concurrent writes), and `scan_iter` inherits
    that. This reproduces it so the dedup in `_get_all` and `count` is covered
    on the core leg, not only against a live server.
    """

    def scan_iter(self, match=None):
        keys = list(super().scan_iter(match=match))
        if keys:
            yield keys[0]
        yield from keys


def test_scan_returning_a_key_twice_is_deduplicated(monkeypatch):
    domain = _install(monkeypatch, _DuplicatingStub())
    with domain.domain_context():
        cache = domain.cache_for(CacheEntry)
        cache.add(CacheEntry(key="k0", value="0"))
        cache.add(CacheEntry(key="k1", value="1"))

        results = cache._get_all(PATTERN)

        # Without dedup the result would be [k0, k0, k1]: the duplicate repeats
        # a projection.
        assert [entry.key for entry in results] == ["k0", "k1"]


def test_count_deduplicates_a_key_scan_returns_twice(monkeypatch):
    domain = _install(monkeypatch, _DuplicatingStub())
    with domain.domain_context():
        cache = domain.cache_for(CacheEntry)
        cache.add(CacheEntry(key="k0", value="0"))
        cache.add(CacheEntry(key="k1", value="1"))

        # `scan_iter` yields k0 twice. Without dedup `count` returns 3 and
        # disagrees with the two distinct entries `_get_all` returns.
        assert cache.count(PATTERN) == 2
