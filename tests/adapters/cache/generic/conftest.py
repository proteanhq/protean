"""Fixtures for the cache port's cross-adapter suite.

The `cache` fixture is parametrized over both configured adapters, so every
test in this package exercises the memory and Redis caches in the same run
against a single shared assertion, the way `tests/adapters/repository/generic`
and `tests/adapters/broker/generic` already do for their ports. The Redis
param carries the `redis` marker, so the root conftest's `--redis` gate
skips it on the core leg and runs it on the `--redis` leg.
"""

import pytest

from protean.core.projection import BaseProjection
from protean.domain import Domain
from protean.fields import Identifier, String
from tests.shared import REDIS_URI

# Distinct from the DB numbers other Redis-backed suites use (0, 2, 3, 4, 5),
# so this suite does not see keys left behind by another suite's run.
REDIS_DB = 6


class CacheEntry(BaseProjection):
    key: Identifier(identifier=True)
    value: String(required=True)


CACHE_CONFIGS = [
    pytest.param({"provider": "memory", "TTL": 300}, id="memory"),
    pytest.param(
        {"provider": "redis", "URI": f"{REDIS_URI}/{REDIS_DB}", "TTL": 300},
        marks=pytest.mark.redis,
        id="redis",
    ),
]


@pytest.fixture(params=CACHE_CONFIGS)
def cache(request):
    """A cache backed by each configured adapter in turn."""
    domain = Domain(name="Test")
    domain.config["caches"]["default"] = request.param
    domain.register(CacheEntry)
    domain.init(traverse=False)

    with domain.domain_context():
        provider = domain.cache_for(CacheEntry)
        yield provider
        if request.param["provider"] == "redis":
            # `flush_all` calls Redis `FLUSHALL`, which clears every database
            # on the server, not just this suite's `REDIS_DB`. Other suites'
            # Redis-backed fixtures live on other DB numbers and may be
            # running concurrently under xdist, so use `FLUSHDB` here to only
            # clear the one this suite owns.
            provider.get_connection().flushdb()
        else:
            provider.flush_all()
        provider.close()
