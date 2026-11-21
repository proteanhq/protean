"""Tests for ``redis_client``, which finds the Redis client behind a broker."""

import sys

import pytest
import redis

from protean.infra.broker import Broker
from protean.port.broker import BrokerCapabilities
from protean.server._redis import redis_client
from tests.shared import REDIS_URI


def test_no_broker_has_no_client():
    assert redis_client(None) is None


def test_inline_broker_has_no_client(test_domain):
    assert redis_client(test_domain.brokers["default"]) is None


class _OtherClientAdapter:
    """Stands in for an adapter whose native client is not a Redis client."""

    capabilities = BrokerCapabilities(0)

    def get_connection(self) -> object:
        return object()


class _FailingConnectionAdapter:
    capabilities = BrokerCapabilities(0)

    def get_connection(self) -> object:
        raise RuntimeError("connection lookup failed")


def test_broker_with_a_non_redis_client_has_no_client():
    broker = Broker(_OtherClientAdapter())  # type: ignore[arg-type]

    assert redis_client(broker) is None


def test_get_connection_errors_are_raised():
    broker = Broker(_FailingConnectionAdapter())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="connection lookup failed"):
        redis_client(broker)


def test_without_the_redis_package_there_is_no_client(monkeypatch):
    """With ``redis`` not installed the broker's connection is never asked for."""
    monkeypatch.setitem(sys.modules, "redis", None)
    broker = Broker(_FailingConnectionAdapter())  # type: ignore[arg-type]

    assert redis_client(broker) is None


@pytest.mark.redis
def test_closed_redis_broker_has_no_client_and_stays_closed(test_domain):
    test_domain.config["brokers"]["redis"] = {
        "provider": "redis",
        "URI": f"{REDIS_URI}/2",
    }
    test_domain.brokers._initialize()
    broker = test_domain.brokers["redis"]

    broker._close()

    assert redis_client(broker) is None
    assert broker._adapter.redis_instance is None


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
