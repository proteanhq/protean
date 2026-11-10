"""Run the example on ``docs/reference/adapters/broker/redis.md``."""

import pytest
import redis

from protean.adapters.broker.redis import RedisBroker
from tests.docs.support import domain_from_config, load_example
from tests.shared import REDIS_URI

pytestmark = [pytest.mark.no_test_domain, pytest.mark.redis]

# Database 7 keeps the example's keys apart from the adapter tests' keys.
REDIS_URL = f"{REDIS_URI}/7"


@pytest.fixture
def example(monkeypatch):
    monkeypatch.setenv("REDIS_URL", REDIS_URL)
    client = redis.Redis.from_url(REDIS_URL)
    client.flushdb()
    yield load_example("adapters/broker/redis/001.py")
    client.flushdb()


def test_message_is_read_and_acknowledged(example):
    assert example.message == {"type": "user.created", "user_id": "123"}
    assert example.acknowledged is True
    client = redis.Redis.from_url(REDIS_URL)
    assert client.xpending("user-events", "welcome-mailer")["pending"] == 0

    with example.domain.domain_context():
        broker = example.domain.brokers["default"]
        assert broker.get_next("user-events", "welcome-mailer") is None


def test_message_is_written_to_a_redis_stream(example):
    client = redis.Redis.from_url(REDIS_URL)

    assert client.type("user-events") == b"stream"
    assert client.xlen("user-events") == 1


def test_pool_settings_reach_the_connection_pool(example):
    with example.domain.domain_context():
        pool = example.domain.brokers["default"].redis_instance.connection_pool

    assert pool.max_connections == 10
    assert pool.connection_kwargs["socket_timeout"] == 5


def test_configuration_shown_sets_the_pool_options(tmp_path, monkeypatch):
    monkeypatch.setenv("REDIS_URL", REDIS_URL)
    domain = domain_from_config("adapters/broker/redis/configuration.toml", tmp_path)
    domain.init(traverse=False)

    with domain.domain_context():
        broker = domain.brokers["default"]

    assert isinstance(broker, RedisBroker)
    pool = broker.redis_instance.connection_pool
    assert pool.connection_kwargs["port"] == int(REDIS_URI.rsplit(":", 1)[1])
    assert pool.connection_kwargs["db"] == 7
    assert pool.max_connections == 10
    assert pool.connection_kwargs["socket_timeout"] == 5


def test_configuration_shown_defaults_to_the_documented_uri(tmp_path, monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    domain = domain_from_config("adapters/broker/redis/configuration.toml", tmp_path)

    assert domain.config["brokers"]["default"]["URI"] == "redis://localhost:6379/0"
