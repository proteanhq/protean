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
        provider.flush_all()
        provider.close()


def pytest_collection_modifyitems(config, items):
    """Deselect the memory param for tests marked `never_expires`.

    The memory cache writes every entry with a TTL
    (`TTLDict.__setitem__`) and cannot represent a key that never expires;
    Redis can. That is a missing capability rather than a disagreement, so
    the test is scoped to Redis instead of xfailed on memory.
    """
    deselected = []
    remaining = []

    for item in items:
        callspec = getattr(item, "callspec", None)
        is_never_expires_on_memory = (
            item.get_closest_marker("never_expires") is not None
            and callspec is not None
            and callspec.params.get("cache", {}).get("provider") == "memory"
        )
        if is_never_expires_on_memory:
            deselected.append(item)
        else:
            remaining.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = remaining
