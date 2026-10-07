"""Run the example on ``docs/reference/adapters/cache/redis.md``."""

import pytest
import redis

from tests.docs.support import load_example
from tests.shared import REDIS_URI

pytestmark = [pytest.mark.no_test_domain, pytest.mark.redis]

# Database 7 keeps the example's keys apart from the adapter tests' keys.
REDIS_URL = f"{REDIS_URI}/7"


@pytest.fixture
def example(monkeypatch):
    monkeypatch.setenv("REDIS_URL", REDIS_URL)
    client = redis.Redis.from_url(REDIS_URL)
    client.flushdb()
    yield load_example("adapters/cache/redis/001.py")
    client.flushdb()


def test_redis_is_reachable(example):
    assert example.reachable is True


def test_cached_projection_is_read_back(example):
    assert isinstance(example.entry, example.OrderSummary)
    assert example.entry.order_id == "ord-123"
    assert example.entry.total == 42.5
    assert example.count == 1


def test_custom_ttl_replaces_the_default(example):
    # Redis reports milliseconds left, so a few may pass before the read
    assert 599.0 < example.remaining <= 600.0


def test_flush_all_empties_the_cache(example):
    with example.domain.domain_context():
        cache = example.domain.cache_for(example.OrderSummary)

        assert cache.get("order_summary:::ord-123") is None
        assert cache.count("order_summary:::*") == 0


def test_entries_land_in_redis_with_the_default_ttl(example):
    with example.domain.domain_context():
        cache = example.domain.cache_for(example.OrderSummary)
        cache.add(example.OrderSummary(order_id="ord-456", total=10.0))

    client = redis.Redis.from_url(REDIS_URL)
    assert client.exists("order_summary:::ord-456") == 1
    # The "TTL": 300 in the config applies to every new entry
    assert 299_000 < client.pttl("order_summary:::ord-456") <= 300_000
