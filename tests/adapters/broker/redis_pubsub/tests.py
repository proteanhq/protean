import json

import pytest
import redis

from protean.adapters.broker import RedisPubSubBroker


@pytest.fixture(autouse=True)
def init_domain(test_domain):
    test_domain.init(traverse=False)


@pytest.mark.redis
class TestRedisConnection:
    def test_that_redis_is_the_configured_broker(self, test_domain):
        assert "default" in test_domain.brokers
        broker = test_domain.brokers["default"]

        assert isinstance(broker, RedisPubSubBroker)
        assert broker.__broker__ == "redis_pubsub"
        assert broker.conn_info["URI"] == "redis://127.0.0.1:6379/0"
        assert broker.redis_instance is not None
        assert isinstance(broker.redis_instance, redis.Redis)


@pytest.mark.redis
class TestPublishingToRedis:
    def test_event_message_structure(self, test_domain):
        channel = "test_channel"
        message = {"key": "value"}

        test_domain.brokers["default"].publish(channel, message)

        # Retrieve with an independent Redis instance
        r = redis.Redis.from_url(test_domain.config["brokers"]["default"]["URI"])
        message = r.lpop(channel)
        assert message is not None

        # Verify Structure
        json_message = json.loads(message)
        assert json_message == {"key": "value"}


@pytest.mark.redis
class TestReceivingFromRedis:
    def test_retrieving_an_event_message(self, test_domain):
        channel = "test_channel"
        message = {"key": "value"}

        test_domain.brokers["default"].publish(channel, message)

        # Retrieve message
        message = test_domain.brokers["default"].get_next(channel)

        # Verify Payload
        assert message is not None
        assert message == {"key": "value"}
