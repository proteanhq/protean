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
        # Use the actual broker configuration from test_domain instead of hard-coded values
        expected_uri = test_domain.config["brokers"]["default"]["URI"]
        assert broker.conn_info["URI"] == expected_uri
        assert broker.redis_instance is not None
        assert isinstance(broker.redis_instance, redis.Redis)


@pytest.mark.redis
class TestPublishingToRedis:
    def test_event_message_structure(self, test_domain):
        stream = "test_stream"
        message = {"key": "value"}

        identifier = test_domain.brokers["default"].publish(stream, message)

        # Verify identifier is returned
        assert identifier is not None
        assert isinstance(identifier, str)
        assert len(identifier) > 0

        # Retrieve with an independent Redis instance
        r = redis.Redis.from_url(test_domain.config["brokers"]["default"]["URI"])
        stored_message = r.lpop(stream)
        assert stored_message is not None

        # Verify Structure - should be stored as tuple (identifier, message)
        json_tuple = json.loads(stored_message)
        assert isinstance(json_tuple, list)  # JSON loads tuples as lists
        assert len(json_tuple) == 2
        assert json_tuple[0] == identifier  # First element is the identifier
        assert json_tuple[1] == {
            "key": "value"
        }  # Second element is the original message


@pytest.mark.redis
class TestReceivingFromRedis:
    def test_retrieving_an_event_message(self, test_domain):
        stream = "test_stream"
        message = {"key": "value"}

        test_domain.brokers["default"].publish(stream, message)

        # Retrieve message
        retrieved_message = test_domain.brokers["default"].get_next(
            stream, "test_consumer_group"
        )

        assert retrieved_message is not None
        assert retrieved_message[0] is not None
        assert retrieved_message[1] == {"key": "value"}
