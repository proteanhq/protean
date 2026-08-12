"""`get_all` on the memory cache guards the TTL-expiry race (#1401).

`get_all` enumerates the matching keys, then reads each one. A key can expire
between the two steps, in which case the read returns `None`. The adapter must
skip it rather than pass `None` into the projection class, which is what the
Redis adapter already does with its own `if raw is not None` guard.

Driven through the memory cache directly so the branch runs on the core suite.
"""

import pytest

from protean.core.projection import BaseProjection
from protean.domain import Domain
from protean.fields import Identifier, String

pytestmark = pytest.mark.no_test_domain


class CacheEntry(BaseProjection):
    key: Identifier(identifier=True)
    value: String(required=True)


PATTERN = "cache_entry:::*"


@pytest.fixture
def cache():
    """A memory cache with `CacheEntry` registered."""
    domain = Domain(name="Test")
    domain.config["caches"]["default"] = {"provider": "memory", "TTL": 300}
    domain.register(CacheEntry)
    domain.init(traverse=False)

    with domain.domain_context():
        yield domain.cache_for(CacheEntry)


def test_a_key_expiring_between_enumeration_and_read_is_skipped(cache, monkeypatch):
    for i in range(3):
        cache.add(CacheEntry(key=f"k{i}", value=str(i)))

    # Simulate the race: the key is still listed by `keys()` but its value has
    # been evicted by the time `get_all` reads it, so `get` returns `None`.
    real_get = cache._db.get
    victim = "cache_entry:::k1"

    def racing_get(key, default=None):
        if key == victim:
            return None
        return real_get(key, default)

    monkeypatch.setattr(cache._db, "get", racing_get)

    page = cache.get_all(PATTERN, last_position=0, size=25)

    # k1's value read back as `None` and was dropped, not turned into
    # `CacheEntry(None)`, which raises `AssertionError`.
    assert [entry.key for entry in page] == ["k0", "k2"]
