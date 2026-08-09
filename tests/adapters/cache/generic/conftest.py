"""Fixtures for the cache port's cross-adapter suite.

The `cache` fixture is parametrized over both configured adapters, so every
test in this package exercises the memory and Redis caches in the same run
against a single shared assertion, the way `tests/adapters/repository/generic`
and `tests/adapters/broker/generic` already do for their ports. The Redis
param carries the `redis` marker, so the root conftest's `--redis` gate
skips it on the core leg and runs it on the `--redis` leg.
"""

from pathlib import Path

import pytest

from protean.core.projection import BaseProjection
from protean.domain import Domain
from protean.fields import Identifier, String
from tests.shared import REDIS_URI

# Distinct from the DB numbers other Redis-backed suites use (0, 2, 3, 4, 5),
# so this suite does not see keys left behind by another suite's run.
REDIS_DB = 6

_SUITE_DIR = Path(__file__).parent


def pytest_collection_modifyitems(items):
    """Every test here builds its own domain via the `cache` fixture, so skip
    the root autouse `test_domain` fixture for this suite to avoid building a
    second, unused domain per test.
    """
    for item in items:
        if _SUITE_DIR in item.path.parents:
            item.add_marker(pytest.mark.no_test_domain)


class CacheEntry(BaseProjection):
    """`Identifier` + `String` only.

    Narrow on purpose, but it means the memory cache's live `to_dict()`
    dict vs Redis' `json.dumps`/`json.loads` round trip is never exercised
    for value shapes where the two diverge (e.g. a `Dict` field with
    integer keys survives on memory but comes back with string keys from
    Redis' JSON round trip). Deliberately deferred, not covered here.
    """

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
