"""Run the example on ``docs/reference/adapters/cache/index.md``."""

import tomllib

import pytest

from protean.adapters.cache.memory import MemoryCache
from protean.adapters.cache.redis import RedisCache
from tests.docs.support import DOCS, DOCS_SRC, domain_from_config, load_example
from tests.shared import REDIS_URI
from tests.support.snippets import expand_includes, extract_toml_blocks

pytestmark = pytest.mark.no_test_domain


def test_ttl_of_a_cached_key_is_reported_in_seconds():
    example = load_example("adapters/cache/index/001.py")

    assert example.present == "60s left"


def test_missing_key_has_no_ttl():
    example = load_example("adapters/cache/index/001.py")

    assert example.missing == "missing"


def test_every_configuration_block_parses_as_toml():
    text = expand_includes(
        (DOCS / "reference/adapters/cache/index.md").read_text(), [DOCS_SRC]
    )
    blocks = [block for block in extract_toml_blocks(text) if not block.fragment]

    assert blocks
    for block in blocks:
        tomllib.loads(block.source)


def test_memory_configuration_shown_builds_a_memory_cache(tmp_path):
    domain = domain_from_config("adapters/cache/index/memory.toml", tmp_path)
    domain.init(traverse=False)

    with domain.domain_context():
        assert type(domain.caches["default"]) is MemoryCache


def _redis_cache(path, tmp_path, monkeypatch, text=None):
    monkeypatch.setenv("REDIS_URL", f"{REDIS_URI}/7")
    domain = domain_from_config(path, tmp_path, text=text)
    domain.init(traverse=False)
    with domain.domain_context():
        cache = domain.caches["default"]
    assert type(cache) is RedisCache
    assert cache.r.connection_pool.connection_kwargs["db"] == 7
    return cache


@pytest.mark.redis
def test_redis_configuration_shown_sets_the_uri_and_ttl(tmp_path, monkeypatch):
    cache = _redis_cache("adapters/cache/index/redis.toml", tmp_path, monkeypatch)

    assert cache.ttl == 300


@pytest.mark.redis
def test_changed_ttl_reaches_the_cache(tmp_path, monkeypatch):
    # 300 is also the default TTL, so a changed value shows the key is read.
    text = (DOCS_SRC / "adapters/cache/index/redis.toml").read_text()
    assert "TTL = 300" in text
    text = text.replace("TTL = 300", "TTL = 120")
    cache = _redis_cache(
        "adapters/cache/index/redis.toml", tmp_path, monkeypatch, text=text
    )

    assert cache.ttl == 120


@pytest.mark.redis
@pytest.mark.parametrize("cache_ttl, ttl", [(None, 3600), ("60", 60)])
def test_ttl_from_the_environment_reaches_the_cache(
    cache_ttl, ttl, tmp_path, monkeypatch
):
    if cache_ttl is None:
        monkeypatch.delenv("CACHE_TTL", raising=False)
    else:
        monkeypatch.setenv("CACHE_TTL", cache_ttl)
    cache = _redis_cache(
        "adapters/cache/index/ttl_from_env.toml", tmp_path, monkeypatch
    )

    assert cache.ttl == ttl


@pytest.mark.parametrize(
    "path",
    ["adapters/cache/index/redis.toml", "adapters/cache/index/ttl_from_env.toml"],
)
def test_redis_configuration_shown_defaults_to_the_documented_uri(
    path, tmp_path, monkeypatch
):
    monkeypatch.delenv("REDIS_URL", raising=False)
    domain = domain_from_config(path, tmp_path)

    assert domain.config["caches"]["default"]["URI"] == "redis://localhost:6379/2"
