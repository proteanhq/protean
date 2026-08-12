"""`get_all` pages Redis keys by a stable sorted offset (#1401).

Redis has no native ordering, so `get_all` collects every matching key with
`scan_iter`, sorts them ascending, then slices `[last_position : last_position +
size]`. That sort and slice is the whole behaviour that made Redis agree with
the memory cache, so it is worth covering on its own.

Driven through a stub client rather than a live Redis, so the pagination logic
runs in the core suite the way `test_redis_ttl_units.py` covers `get_ttl`. The
cross-adapter `TestGetAllPaginationAgrees` in `generic/test_key_patterns.py`
still pins the same contract against a real Redis on the `--redis` leg.
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
    """The parts of the Redis client `get_all`/`add` touch, backed by a dict.

    Keys and values come back as `bytes`, the way redis-py answers without
    `decode_responses`, so the test exercises the same bytes sort the live
    adapter does. `scan_iter` yields keys in insertion order, deliberately not
    sorted, so a `get_all` that forgot to sort would return them in the wrong
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


def test_offsets_tile_the_result_set_in_one_stable_order(cache):
    _load(cache)

    walked = []
    for n in range(COUNT):
        walked.extend(cache.get_all(PATTERN, last_position=n, size=1))

    single_page = cache.get_all(PATTERN, last_position=0, size=COUNT)

    assert [entry.key for entry in walked] == EXPECTED_ORDER
    assert [entry.key for entry in single_page] == EXPECTED_ORDER


def test_size_is_a_hard_cap(cache):
    _load(cache)

    assert len(cache.get_all(PATTERN, last_position=0, size=5)) == 5
    # Two entries left past offset 18, fewer than the size-5 request.
    assert len(cache.get_all(PATTERN, last_position=18, size=5)) == 2


def test_past_the_end_is_empty(cache):
    _load(cache)

    assert cache.get_all(PATTERN, last_position=COUNT, size=5) == []
    assert cache.get_all(PATTERN, last_position=COUNT + 100, size=5) == []


class _DuplicatingStub(_StubClient):
    """A stub whose `scan_iter` yields the first matching key twice.

    Redis `SCAN` is documented to return the same element more than once during
    a full iteration (rehashing, concurrent writes), and `scan_iter` inherits
    that. This reproduces it so the dedup in `get_all` is covered on the core
    leg, not only against a live server.
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

        page = cache.get_all(PATTERN, last_position=0, size=25)

        # Without dedup the page would be [k0, k0, k1]: the duplicate repeats a
        # projection and shifts every later offset.
        assert [entry.key for entry in page] == ["k0", "k1"]
