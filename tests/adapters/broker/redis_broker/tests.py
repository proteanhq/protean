import json

import pytest
import redis

from protean.adapters.broker.redis import RedisBroker
from protean.globals import current_domain
from protean.server import Server

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
    @pytest.mark.asyncio
    async def test_event_message_structure(self, test_domain):
        # Publish event
        event = PersonAdded(id="1234", first_name="John", last_name="Doe", age=24,)
        test_domain.publish(event)

        # Push to Redis
        server = Server(domain=test_domain, test_mode=True)
        await server.push_messages()
        server.stop()

        # Retrieve with an independent Redis instance
        r = redis.Redis.from_url(test_domain.config["BROKERS"]["default"]["URI"])
        message = r.lpop("messages")
        assert message is not None

        # Verify Structure
        json_message = json.loads(message)
        assert all(
            key in json_message
            for key in [
                "message_id",
                "name",
                "type",
                "created_at",
                "owner",
                "version",
                "payload",
            ]
        )
        assert json_message["type"] == "EVENT"

    @pytest.mark.asyncio
    async def test_that_an_event_can_be_published_to_redis(self, test_domain):
        # Publish event
        event = PersonAdded(id="1234", first_name="John", last_name="Doe", age=24,)
        test_domain.publish(event)

        # Push to Redis
        server = Server(domain=test_domain, test_mode=True)
        await server.push_messages()
        server.stop()

        # Retrieve with an independent Redis instance
        r = redis.Redis.from_url(test_domain.config["BROKERS"]["default"]["URI"])
        message = r.lpop("messages")
        assert message is not None

        # Verify Payload
        json_message = json.loads(message)
        assert "payload" in json_message
        assert "id" in json_message["payload"]
        assert json_message["payload"]["id"] == event.id

    @pytest.mark.skip(reason="Yet to implement")
    def test_command_message_structure(self):
        pass

    @pytest.mark.skip(reason="Yet to implement")
    def test_that_a_command_can_be_published_to_redis(self):
        pass


@pytest.mark.redis
class TestReceivingFromRedis:
    def test_for_no_error_on_no_message(self, test_domain):
        message = test_domain.brokers["default"].get_next()
        assert message is None

    @pytest.mark.asyncio
    async def test_retrieving_an_event_message(self, test_domain):
        # Publish event
        event = PersonAdded(id="1234", first_name="John", last_name="Doe", age=24,)
        test_domain.publish(event)

        # Push to Redis
        server = Server(domain=test_domain, test_mode=True)
        await server.push_messages()
        server.stop()

        # Retrieve event
        message = test_domain.brokers["default"].get_next()

        # Verify Payload
        assert "payload" in message
        assert "id" in message["payload"]
        assert message["payload"]["id"] == event.id

    @pytest.mark.asyncio
    async def test_reconstructing_an_event_object_from_message(self, test_domain):
        test_domain.register(PersonAdded)

        # Publish event
        event = PersonAdded(id="1234", first_name="John", last_name="Doe", age=24,)
        test_domain.publish(event)

        # Push to Redis
        server = Server(domain=test_domain, test_mode=True)
        await server.push_messages()
        server.stop()

        # Retrieve message
        message = test_domain.brokers["default"].get_next()

        # Verify reconstructed event object
        retrieved_event = test_domain.from_message(message)
        assert retrieved_event == event

    @pytest.mark.skip(reason="Yet to implement")
    def test_retrieving_a_command_message(self):
        pass

    @pytest.mark.skip(reason="Yet to implement")
    def test_reconstructing_a_command_object_from_message(self):
        pass
