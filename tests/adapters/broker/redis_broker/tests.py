import pytest
import redis

from protean.adapters.broker.redis import RedisBroker
from protean.globals import current_domain


@pytest.mark.redis
class TestRedisConnection:
    def test_that_configured_broker_is_celery_with_redis(self):
        assert "default" in current_domain.brokers
        broker = current_domain.brokers["default"]

        assert isinstance(broker, RedisBroker)
        assert broker.conn_info["URI"] == "redis://127.0.0.1:6379/0"
        assert broker.conn_pool is not None
        assert isinstance(broker.conn_pool, redis.ConnectionPool)

    def test_that_connection_can_be_retrieved_from_pool(self):
        broker = current_domain.brokers["default"]

        connection = broker.get_connection()
        assert isinstance(connection, redis.Connection)

        try:
            connection.check_health()
        except redis.ConnectionError:
            pytest.fail("ConnectionError during redis health check")

    def test_that_connection_is_no_longer_active_after_release(self):
        broker = current_domain.brokers["default"]

        connection = broker.get_connection()
        assert connection in broker.conn_pool._in_use_connections

        broker.release_connection(connection)
        assert connection not in broker.conn_pool._in_use_connections


@pytest.mark.redis
class TestPublishingToRedis:
    def test_that_an_event_can_be_published_to_redis(self):
        pass

    def test_that_a_command_can_be_published_to_redis(self):
        pass

    def test_event_message_structure(self):
        pass

    def test_command_message_structure(self):
        pass


@pytest.mark.redis
class TestReceivingFromRedis:
    def test_retrieving_an_event_message(self):
        pass

    def test_retrieving_a_command_message(self):
        pass

    def test_reconstructing_an_event_object_from_message(self):
        pass

    def test_reconstructing_a_command_object_from_message(self):
        pass
