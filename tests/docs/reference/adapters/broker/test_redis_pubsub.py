"""Run the example on ``docs/reference/adapters/broker/redis-pubsub.md``."""

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
