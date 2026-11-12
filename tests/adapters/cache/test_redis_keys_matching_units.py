"""`RedisCache.keys_matching` returns distinct keys, sorted, decoded as UTF-8.

Redis has no native ordering, so `keys_matching` collects every matching key
with `scan_iter`, dedupes, sorts the raw bytes ascending, then decodes them.
That sort, dedupe and decode is the whole behaviour, so it is worth covering
on its own.

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


def _encoded(key: str | bytes) -> bytes:
    return key if isinstance(key, bytes) else key.encode()


class _StubClient:
    """The parts of the Redis client `put`/`get`/`keys_matching` touch, backed
    by a dict.

    Keys and values come back as `bytes`, the way redis-py answers without
    `decode_responses`, so the test exercises the same bytes sort the live
    adapter does. `scan_iter` yields keys in insertion order, deliberately not
    sorted, so a `keys_matching` that forgot to sort would return them in the
    wrong order and the order assertion would catch it.
    """

    def __init__(self) -> None:
        self._store: dict[bytes, bytes] = {}

    def ping(self) -> bool:
        return True

    def psetex(self, key: str, ttl_ms: int, value: str) -> None:
        self._store[_encoded(key)] = value.encode()

    def scan_iter(self, match: str | None = None):
        for key in self._store:  # insertion order, not sorted
            if match is None or fnmatch.fnmatchcase(key.decode("latin-1"), match):
                yield key

    def get(self, key: str | bytes) -> bytes | None:
        return self._store.get(_encoded(key))


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


def test_keys_matching_returns_every_match_in_key_order_as_str(cache):
    _load(cache)

    keys = cache._adapter.keys_matching(PATTERN)

    assert keys == [f"cache_entry:::{key}" for key in EXPECTED_ORDER]
    assert all(isinstance(key, str) for key in keys)


def test__get_all_returns_every_match_in_key_order(cache):
    _load(cache)

    results = cache._get_all(PATTERN)

    assert [entry.key for entry in results] == EXPECTED_ORDER


def test_keys_matching_sorts_non_ascii_keys_by_code_point(cache):
    """UTF-8 byte order is code-point order, so sorting the raw bytes and
    then decoding gives the same order as the memory adapter's `str` sort."""
    adapter = cache._adapter
    for key in ["k:::é", "k:::z", "k:::a", "k:::日"]:
        adapter.put(key, {"key": key}, 60.0)

    assert adapter.keys_matching("k:::*") == sorted(
        ["k:::é", "k:::z", "k:::a", "k:::日"]
    )


def test_a_key_that_is_not_utf8_raises(monkeypatch):
    """The `Cache` service writes every key as a `str`, so a key that does not
    decode was written by another client and is not silently mangled."""
    stub = _StubClient()
    stub._store[b"cache_entry:::\xff"] = b"{}"
    domain = _install(monkeypatch, stub)
    with domain.domain_context():
        adapter = domain.caches["default"]._adapter

        with pytest.raises(UnicodeDecodeError):
            adapter.keys_matching(PATTERN)


class _DuplicatingStub(_StubClient):
    """A stub whose `scan_iter` yields the first matching key twice.

    Redis `SCAN` is documented to return the same element more than once during
    a full iteration (rehashing, concurrent writes), and `scan_iter` inherits
    that. This reproduces it so the dedup in `keys_matching` and
    `count_matching` is covered on the core leg, not only against a live server.
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

        # Without dedup the result would be [k0, k0, k1].
        assert cache._adapter.keys_matching(PATTERN) == [
            "cache_entry:::k0",
            "cache_entry:::k1",
        ]
        assert [entry.key for entry in cache._get_all(PATTERN)] == ["k0", "k1"]


def test_count_deduplicates_a_key_scan_returns_twice(monkeypatch):
    domain = _install(monkeypatch, _DuplicatingStub())
    with domain.domain_context():
        cache = domain.cache_for(CacheEntry)
        cache.add(CacheEntry(key="k0", value="0"))
        cache.add(CacheEntry(key="k1", value="1"))

        # `scan_iter` yields k0 twice. Without dedup `count` returns 3 and
        # disagrees with the two distinct keys `keys_matching` returns.
        assert cache.count(PATTERN) == 2
