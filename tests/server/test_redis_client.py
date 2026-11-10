"""Tests for ``redis_client``, which finds the Redis client behind a broker."""

import pytest
import redis

from protean.server._redis import redis_client
from tests.shared import REDIS_URI


def test_no_broker_has_no_client():
    assert redis_client(None) is None


def test_inline_broker_has_no_client(test_domain):
    assert redis_client(test_domain.brokers["default"]) is None


@pytest.mark.redis
def test_redis_broker_returns_its_client(test_domain):
    test_domain.config["brokers"]["redis"] = {
        "provider": "redis",
        "URI": f"{REDIS_URI}/2",
    }
    test_domain.brokers._initialize()
    broker = test_domain.brokers["redis"]

    client = redis_client(broker)

    assert isinstance(client, redis.Redis)
    assert client is broker._adapter.redis_instance
