"""Run the example on ``docs/reference/adapters/broker/redis-pubsub.md``."""

import pytest
import redis

from protean.adapters.broker.redis import RedisBroker
from protean.adapters.broker.redis_pubsub import RedisPubSubBroker
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
    yield load_example("adapters/broker/redis-pubsub/001.py")
    client.flushdb()


def test_subscriber_receives_the_notification(example):
    assert example.pushed == [("123", "New Message")]


def test_messages_are_kept_in_a_redis_list(example):
    client = redis.Redis.from_url(REDIS_URL)

    assert client.type("orders") == b"list"
    assert client.llen("orders") == 1


def test_each_group_keeps_its_own_position(example):
    expected = {"type": "order.created", "order_id": "A1"}
    assert example.billing_message == expected
    assert example.shipping_message == expected

    client = redis.Redis.from_url(REDIS_URL)
    assert client.get("position:orders:billing") == b"1"
    assert client.get("position:orders:shipping") == b"1"

    # Both groups have read past the only message
    with example.domain.domain_context():
        broker = example.domain.brokers["notifications"]
        assert broker.get_next("orders", "billing") is None


def test_ack_is_not_supported(example):
    assert example.acknowledged is False


def test_health_check_reads_redis_details(example):
    assert example.health["status"] == "healthy"
    assert isinstance(example.health["connected_clients"], int)
    assert example.health["used_memory"].endswith(("B", "K", "M", "G"))


@pytest.mark.parametrize(
    "path, broker_class",
    [
        ("adapters/broker/redis-pubsub/configuration.toml", RedisPubSubBroker),
        ("adapters/broker/redis-pubsub/before.toml", RedisPubSubBroker),
        ("adapters/broker/redis-pubsub/after.toml", RedisBroker),
    ],
    ids=["configuration", "before", "after"],
)
def test_configuration_shown_builds_the_notifications_broker(
    path, broker_class, tmp_path, monkeypatch
):
    monkeypatch.setenv("REDIS_URL", REDIS_URL)
    domain = domain_from_config(path, tmp_path)
    domain.init(traverse=False)

    with domain.domain_context():
        broker = domain.brokers["notifications"]

    assert type(broker) is broker_class
    kwargs = broker.redis_instance.connection_pool.connection_kwargs
    assert kwargs["port"] == int(REDIS_URI.rsplit(":", 1)[1])
    assert kwargs["db"] == 7


@pytest.mark.parametrize(
    "path",
    [
        "adapters/broker/redis-pubsub/configuration.toml",
        "adapters/broker/redis-pubsub/before.toml",
        "adapters/broker/redis-pubsub/after.toml",
    ],
    ids=["configuration", "before", "after"],
)
def test_configuration_shown_defaults_to_the_documented_uri(
    path, tmp_path, monkeypatch
):
    monkeypatch.delenv("REDIS_URL", raising=False)
    domain = domain_from_config(path, tmp_path)

    uri = domain.config["brokers"]["notifications"]["URI"]
    assert uri == "redis://localhost:6379/0"
