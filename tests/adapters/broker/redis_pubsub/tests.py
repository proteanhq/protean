import pytest

from protean.adapters.broker import RedisPubSubBroker


@pytest.mark.redis
class TestRedisConnectionAndConfiguration:
    def test_that_redis_is_the_configured_broker(self, test_domain):
        """Test Redis-specific broker configuration and instance type"""
        assert "default" in test_domain.brokers
        broker = test_domain.brokers["default"]

        assert isinstance(broker, RedisPubSubBroker)
        assert broker.__broker__ == "redis_pubsub"
        expected_uri = test_domain.config["brokers"]["default"]["URI"]
        assert broker.conn_info["URI"] == expected_uri
        assert broker.redis_instance is not None

    def test_broker_capabilities_simple_queuing(self, broker):
        """Test that broker reports simple queuing capabilities"""
        from protean.port.broker import BrokerCapabilities

        assert broker.capabilities == BrokerCapabilities.SIMPLE_QUEUING

    def test_redis_specific_health_stats_configuration(self, broker):
        """Test Redis-specific health stats configuration"""
        stats = broker.health_stats()

        # Configuration should be under details
        assert "details" in stats
        details = stats["details"]
        assert "configuration" in details

        config = details["configuration"]
        assert config["broker_type"] == "redis_pubsub"
        assert config["native_consumer_groups"] is False
        assert config["native_ack_nack"] is False
        assert config["simple_queuing_only"] is True

    def test_redis_specific_health_stats_redis_info(self, broker):
        """Test that health stats include Redis-specific information"""
        stats = broker.health_stats()

        # Redis info should be under details
        assert "details" in stats
        details = stats["details"]

        # Should include Redis-specific keys
        assert "used_memory" in details
        assert "used_memory_human" in details
        assert "keyspace_hits" in details
        assert "keyspace_misses" in details
        assert "connected_clients" in details
        assert "hit_rate" in details


@pytest.mark.redis
class TestRedisSpecificBehavior:
    def test_redis_message_uuid_format(self, broker):
        """Test that Redis broker generates UUID format identifiers"""
        stream = "test_stream"
        message = {"key": "value"}

        identifier = broker.publish(stream, message)

        # Should be a UUID string (36 characters with 4 hyphens)
        assert isinstance(identifier, str)
        assert len(identifier) == 36
        assert identifier.count("-") == 4

    def test_ack_not_supported_returns_false(self, broker):
        """Test that ACK operations return False for simple queuing broker"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"data": "test"}

        # Publish and get message
        identifier = broker.publish(stream, message)
        retrieved_message = broker.get_next(stream, consumer_group)
        assert retrieved_message is not None

        # ACK should not be supported
        ack_result = broker.ack(stream, identifier, consumer_group)
        assert ack_result is False

    def test_nack_not_supported_returns_false(self, broker):
        """Test that NACK operations return False for simple queuing broker"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"data": "test"}

        # Publish and get message
        identifier = broker.publish(stream, message)
        retrieved_message = broker.get_next(stream, consumer_group)
        assert retrieved_message is not None

        # NACK should not be supported
        nack_result = broker.nack(stream, identifier, consumer_group)
        assert nack_result is False
