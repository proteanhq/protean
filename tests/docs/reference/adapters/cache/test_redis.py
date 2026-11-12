"""Run the example on ``docs/reference/adapters/cache/redis.md``."""

import pytest
import redis

from protean.adapters.cache.redis import RedisCache
from tests.docs.support import DOCS_SRC, domain_from_config, load_example
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


def test_clear_empties_the_cache(example):
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


def _cache_from(path, tmp_path, monkeypatch, text=None):
    monkeypatch.setenv("REDIS_URL", REDIS_URL)
    domain = domain_from_config(path, tmp_path, text=text)
    domain.init(traverse=False)
    with domain.domain_context():
        cache = domain.caches["default"]
    assert type(cache._adapter) is RedisCache
    assert cache._adapter.r.connection_pool.connection_kwargs["db"] == 7
    return cache


def test_configuration_shown_sets_the_uri_and_ttl(tmp_path, monkeypatch):
    cache = _cache_from(
        "adapters/cache/redis/configuration.toml", tmp_path, monkeypatch
    )

    assert cache._resolved_ttl(None) == 300


def test_changed_ttl_reaches_the_cache(tmp_path, monkeypatch):
    # 300 is also the default TTL, so a changed value shows the key is read.
    text = (DOCS_SRC / "adapters/cache/redis/configuration.toml").read_text()
    assert "TTL = 300" in text
    text = text.replace("TTL = 300", "TTL = 120")
    cache = _cache_from(
        "adapters/cache/redis/configuration.toml", tmp_path, monkeypatch, text=text
    )

    assert cache._resolved_ttl(None) == 120


@pytest.mark.parametrize("cache_ttl, ttl", [(None, 3600), ("60", 60)])
def test_ttl_from_the_environment_reaches_the_cache(
    cache_ttl, ttl, tmp_path, monkeypatch
):
    if cache_ttl is None:
        monkeypatch.delenv("CACHE_TTL", raising=False)
    else:
        monkeypatch.setenv("CACHE_TTL", cache_ttl)
    cache = _cache_from("adapters/cache/redis/ttl_from_env.toml", tmp_path, monkeypatch)

    assert cache._resolved_ttl(None) == ttl


@pytest.mark.parametrize(
    "path",
    [
        "adapters/cache/redis/configuration.toml",
        "adapters/cache/redis/ttl_from_env.toml",
    ],
)
def test_configuration_shown_defaults_to_the_documented_uri(
    path, tmp_path, monkeypatch
):
    monkeypatch.delenv("REDIS_URL", raising=False)
    domain = domain_from_config(path, tmp_path)

    assert domain.config["caches"]["default"]["URI"] == "redis://localhost:6379/2"
