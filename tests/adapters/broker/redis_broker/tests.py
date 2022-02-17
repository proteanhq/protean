import json

import pytest
import redis

from protean.adapters.broker.redis import RedisBroker
from protean.globals import current_domain

from .elements import PersonAdded


@pytest.mark.redis
class TestRedisConnection:
    def test_that_redis_is_the_configured_broker(self):
        assert "default" in current_domain.brokers
        broker = current_domain.brokers["default"]

        assert isinstance(broker, RedisBroker)
        assert broker.conn_info["URI"] == "redis://127.0.0.1:6379/0"
        assert broker.redis_instance is not None
        assert isinstance(broker.redis_instance, redis.Redis)


@pytest.mark.redis
class TestPublishingToRedis:
    def test_event_message_structure(self, test_domain):
        # Publish event
        event = PersonAdded(
            id="1234",
            first_name="John",
            last_name="Doe",
            age=24,
        )
        test_domain.publish(event)

        # Retrieve with an independent Redis instance
        r = redis.Redis.from_url(test_domain.config["BROKERS"]["default"]["URI"])
        message = r.lpop("messages")
        assert message is not None

        # Verify Structure
        json_message = json.loads(message)
        assert all(
            key in json_message
            for key in [
                "global_position",
                "position",
                "time",
                "id",
                "stream_name",
                "type",
                "data",
                "metadata",
            ]
        )
        assert json_message["type"] == "redis_broker.elements.PersonAdded"
        assert json_message["metadata"]["kind"] == "EVENT"


@pytest.mark.redis
class TestReceivingFromRedis:
    def test_for_no_error_on_no_message(self, test_domain):
        message = test_domain.brokers["default"].get_next()
        assert message is None

    def test_retrieving_an_event_message(self, test_domain):
        # Publish event
        event = PersonAdded(
            id="1234",
            first_name="John",
            last_name="Doe",
            age=24,
        )
        test_domain.publish(event)

        # Retrieve event
        message = test_domain.brokers["default"].get_next()

        # Verify Payload
        assert message is not None
        assert message.data["id"] == event.id

    def test_reconstructing_an_event_object_from_message(self, test_domain):
        test_domain.register(PersonAdded)

        # Publish event
        event = PersonAdded(
            id="1234",
            first_name="John",
            last_name="Doe",
            age=24,
        )
        test_domain.publish(event)

        # Retrieve message
        message = test_domain.brokers["default"].get_next()

        # Verify reconstructed event object
        retrieved_event = message.to_object()
        assert retrieved_event == event
