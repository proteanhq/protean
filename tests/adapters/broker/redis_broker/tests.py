import pytest
import redis

from protean.adapters.broker.redis import RedisBroker
from protean.globals import current_domain


@pytest.mark.redis
class TestRedisConnection:
    def test_that_redis_is_the_configured_broker(self):
        assert "default" in current_domain.brokers
        broker = current_domain.brokers["default"]

        assert isinstance(broker, RedisBroker)
        assert broker.conn_info["URI"] == "redis://127.0.0.1:6379/0"
        assert broker.redis_instance is not None
        assert isinstance(broker.redis_instance, redis.Redis)
