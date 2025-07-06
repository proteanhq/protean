"""Redis-specific tests focused on Redis PubSub broker behavior and edge cases"""

import logging
from unittest.mock import patch

import pytest
import redis


@pytest.mark.redis
class TestRedisConnectionHandling:
    """Test Redis connection-specific behavior"""

    def test_redis_connection_instance_type(self, broker):
        """Test that broker uses actual Redis instance"""
        assert isinstance(broker.redis_instance, redis.Redis)
        assert broker.redis_instance is not None

    def test_redis_connection_from_uri(self, test_domain):
        """Test that Redis connection is created from URI"""
        broker = test_domain.brokers["default"]
        expected_uri = test_domain.config["brokers"]["default"]["URI"]
        assert broker.conn_info["URI"] == expected_uri


@pytest.mark.redis
class TestRedisHealthAndStats:
    """Test Redis-specific health and stats functionality"""

    def test_health_stats_includes_redis_info(self, broker):
        """Test that Redis health stats include Redis server information"""
        stats = broker.health_stats()

        # Check that Redis info is available under details
        assert "details" in stats
        details = stats["details"]

        # Check for Redis-specific metrics
        assert "used_memory" in details
        assert "used_memory_human" in details
        assert "connected_clients" in details
        assert "keyspace_hits" in details
        assert "keyspace_misses" in details
        assert "hit_rate" in details
        assert isinstance(details["used_memory"], int)
        assert isinstance(details["used_memory_human"], str)

    def test_health_stats_configuration_for_redis_pubsub(self, broker):
        """Test that Redis PubSub broker reports correct configuration"""
        stats = broker.health_stats()

        # Check that configuration is available under details
        assert "details" in stats
        details = stats["details"]
        assert "configuration" in details

        config = details["configuration"]
        assert config["broker_type"] == "redis_pubsub"
        assert config["native_consumer_groups"] is False
        assert config["native_ack_nack"] is False
        assert config["simple_queuing_only"] is True

    def test_message_count_calculation_uses_redis_llen(self, broker):
        """Test that message count calculation uses Redis LLEN"""
        # Create consumer groups to track the streams
        broker.get_next("test_stream", "test_group")
        broker.get_next("another_stream", "another_group")

        # Publish some messages
        broker.publish("test_stream", {"message": "test1"})
        broker.publish("test_stream", {"message": "test2"})
        broker.publish("another_stream", {"message": "test3"})

        stats = broker.health_stats()

        # Check that message counts are available under details
        assert "details" in stats
        details = stats["details"]
        assert "message_counts" in details

        message_counts = details["message_counts"]
        assert "total_messages" in message_counts
        assert isinstance(message_counts["total_messages"], int)
        assert (
            message_counts["total_messages"] >= 3
        )  # At least the messages we published

    def test_consumer_group_tracking_in_health_stats(self, broker):
        """Test that consumer group information is tracked in health stats"""
        # Create some consumer groups
        broker.get_next("test_stream", "group1")
        broker.get_next("test_stream", "group2")
        broker.get_next("another_stream", "group3")

        stats = broker.health_stats()

        # Check that consumer group info is available under details
        assert "details" in stats
        details = stats["details"]
        assert "consumer_groups" in details

        cg_info = details["consumer_groups"]
        assert "count" in cg_info
        assert "names" in cg_info
        assert cg_info["count"] >= 3  # At least the groups we created
        assert isinstance(cg_info["names"], list)

    def test_health_stats_hit_rate_calculation_with_hits_and_misses(self, broker):
        """Test hit rate calculation when there are hits and misses"""
        # Mock Redis info to return specific hit/miss values
        mock_redis_info = {
            "connected_clients": 1,
            "used_memory": 1024,
            "used_memory_human": "1K",
            "keyspace_hits": 100,
            "keyspace_misses": 50,
            "loading": 0,
            "rejected_connections": 0,
        }

        with patch.object(broker.redis_instance, "info", return_value=mock_redis_info):
            stats = broker.health_stats()

            # Check that hit rate is calculated correctly
            assert "details" in stats
            details = stats["details"]
            assert "hit_rate" in details

            # Hit rate should be hits / (hits + misses) = 100 / (100 + 50) = 0.6667
            expected_hit_rate = 100 / (100 + 50)
            assert abs(details["hit_rate"] - expected_hit_rate) < 0.0001

    def test_health_stats_hit_rate_calculation_with_no_hits_or_misses(self, broker):
        """Test hit rate calculation when there are no hits or misses"""
        # Mock Redis info to return zero hits and misses
        mock_redis_info = {
            "connected_clients": 1,
            "used_memory": 1024,
            "used_memory_human": "1K",
            "keyspace_hits": 0,
            "keyspace_misses": 0,
            "loading": 0,
            "rejected_connections": 0,
        }

        with patch.object(broker.redis_instance, "info", return_value=mock_redis_info):
            stats = broker.health_stats()

            # Check that hit rate is set to 0.0
            assert "details" in stats
            details = stats["details"]
            assert "hit_rate" in details
            assert details["hit_rate"] == 0.0

    def test_health_stats_detects_loading_state(self, broker):
        """Test that health stats detects when Redis is loading data from disk"""
        # Mock Redis info to indicate loading state
        mock_redis_info = {
            "connected_clients": 1,
            "used_memory": 1024,
            "used_memory_human": "1K",
            "keyspace_hits": 10,
            "keyspace_misses": 5,
            "loading": 1,  # Redis is loading data from disk
            "rejected_connections": 0,
        }

        with patch.object(broker.redis_instance, "info", return_value=mock_redis_info):
            stats = broker.health_stats()

            # Check that loading state is detected
            assert "details" in stats
            details = stats["details"]
            assert details["healthy"] is False
            assert "warning" in details
            assert "Redis is loading data from disk" in details["warning"]

    def test_health_stats_detects_rejected_connections(self, broker):
        """Test that health stats detects when Redis has rejected connections"""
        # Mock Redis info to indicate rejected connections
        mock_redis_info = {
            "connected_clients": 1,
            "used_memory": 1024,
            "used_memory_human": "1K",
            "keyspace_hits": 10,
            "keyspace_misses": 5,
            "loading": 0,
            "rejected_connections": 5,  # Redis has rejected connections
        }

        with patch.object(broker.redis_instance, "info", return_value=mock_redis_info):
            stats = broker.health_stats()

            # Check that rejected connections are detected
            assert "details" in stats
            details = stats["details"]
            assert details["healthy"] is False
            assert "warning" in details
            assert "Redis has rejected connections" in details["warning"]

    def test_health_stats_exception_handling(self, broker, caplog):
        """Test that _health_stats method handles exceptions properly"""
        # Mock Redis instance to raise exception when calling info()
        with patch.object(broker.redis_instance, "info") as mock_info:
            mock_info.side_effect = redis.ConnectionError("Connection failed")

            # Clear any existing logs
            caplog.clear()

            # Set log level to capture error messages
            with caplog.at_level(logging.ERROR):
                # Call health_stats which should handle the exception
                stats = broker.health_stats()

                # Should return error stats structure
                assert "details" in stats
                details = stats["details"]
                assert details["healthy"] is False
                assert "error" in details
                assert "Connection failed" in details["error"]
                assert "message_counts" in details
                assert details["message_counts"]["total_messages"] == 0
                assert "consumer_groups" in details
                assert details["consumer_groups"]["count"] == 0
                assert details["consumer_groups"]["names"] == []
                assert "configuration" in details
                assert details["configuration"]["broker_type"] == "redis_pubsub"
                assert "error" in details["configuration"]
                assert (
                    "Failed to get configuration" in details["configuration"]["error"]
                )
                assert details["configuration"]["simple_queuing_only"] is True

                # Should log error message
                assert len(caplog.records) == 1
                assert caplog.records[0].levelname == "ERROR"
                assert (
                    "Error getting Redis PubSub health stats"
                    in caplog.records[0].message
                )
                assert "Connection failed" in caplog.records[0].message


@pytest.mark.redis
class TestRedisDataReset:
    """Test Redis-specific data reset behavior"""

    def test_data_reset_clears_consumer_groups(self, broker):
        """Test that data reset clears internal consumer group tracking"""
        # Create consumer groups
        broker.get_next("test_stream", "group1")
        broker.get_next("test_stream", "group2")

        # Verify groups exist
        assert len(broker._consumer_groups) >= 2

        # Reset data
        broker._data_reset()

        # Verify groups are cleared
        assert len(broker._consumer_groups) == 0

    def test_data_reset_clears_redis_streams(self, broker):
        """Test that data reset clears Redis streams"""
        # Publish messages
        broker.publish("test_stream", {"message": "test1"})
        broker.publish("test_stream", {"message": "test2"})

        # Verify messages exist
        assert broker.redis_instance.llen("test_stream") >= 2

        # Reset data
        broker._data_reset()

        # Verify streams are cleared
        assert broker.redis_instance.llen("test_stream") == 0

    def test_data_reset_exception_handling(self, broker, caplog):
        """Test that _data_reset method handles exceptions properly"""
        # Create some consumer groups to verify they get cleared even with exceptions
        broker.get_next("test_stream", "test_group")

        # Mock Redis instance to raise exception when calling flushall()
        with patch.object(broker.redis_instance, "flushall") as mock_flushall:
            mock_flushall.side_effect = redis.ConnectionError("Connection failed")

            # Clear any existing logs
            caplog.clear()

            # Set log level to capture error messages
            with caplog.at_level(logging.ERROR):
                # Call _data_reset which should handle the exception
                broker._data_reset()

                # Consumer groups should NOT be cleared if Redis flushall fails
                # because clear() is called in the try block after flushall()
                assert len(broker._consumer_groups) == 1

                # Should log error message
                assert len(caplog.records) == 1
                assert caplog.records[0].levelname == "ERROR"
                assert "Error during data reset" in caplog.records[0].message
                assert "Connection failed" in caplog.records[0].message


@pytest.mark.redis
class TestRedisErrorHandling:
    """Test Redis-specific error handling behavior"""

    def test_redis_response_error_handling(self, broker):
        """Test that Redis ResponseError is properly raised"""
        # Mock Redis instance to raise ResponseError
        with patch.object(broker.redis_instance, "lindex") as mock_lindex:
            mock_lindex.side_effect = redis.ResponseError("Invalid operation")

            # The broker should let the Redis exception bubble up
            with pytest.raises(redis.ResponseError, match="Invalid operation"):
                broker.get_next("test_stream", "test_group")

    def test_redis_timeout_error_handling(self, broker):
        """Test that Redis TimeoutError is properly raised"""
        # Mock Redis instance to raise TimeoutError
        with patch.object(broker.redis_instance, "lindex") as mock_lindex:
            mock_lindex.side_effect = redis.TimeoutError("Operation timed out")

            # The broker should let the Redis exception bubble up
            with pytest.raises(redis.TimeoutError, match="Operation timed out"):
                broker.get_next("test_stream", "test_group")

    def test_ping_exception_handling(self, broker, caplog):
        """Test that _ping method handles exceptions properly"""
        # Mock Redis instance to raise exception on ping
        with patch.object(broker.redis_instance, "ping") as mock_ping:
            mock_ping.side_effect = redis.ConnectionError("Connection failed")

            # Clear any existing logs
            caplog.clear()

            # Set log level to capture debug messages
            with caplog.at_level(logging.DEBUG):
                # Call ping which should handle the exception
                result = broker._ping()

                # Should return False when exception occurs
                assert result is False

                # Should log debug message about the failure
                assert len(caplog.records) == 1
                assert caplog.records[0].levelname == "DEBUG"
                assert "Redis PubSub ping failed" in caplog.records[0].message
                assert "Connection failed" in caplog.records[0].message

    def test_calculate_message_counts_exception_handling(self, broker, caplog):
        """Test that _calculate_message_counts method handles exceptions properly"""
        # Create consumer groups and streams to track
        broker.get_next("test_stream", "test_group")
        broker.get_next("another_stream", "another_group")

        # Mock Redis llen to raise exception
        with patch.object(broker.redis_instance, "llen") as mock_llen:
            mock_llen.side_effect = redis.ConnectionError("Connection failed")

            # Clear any existing logs
            caplog.clear()

            # Set log level to capture debug messages
            with caplog.at_level(logging.DEBUG):
                # Call _calculate_message_counts which should handle the exception
                result = broker._calculate_message_counts()

                # Should return default counts when exception occurs
                assert result == {"total_messages": 0}

                # Should log debug message about the failure
                assert len(caplog.records) == 1
                assert caplog.records[0].levelname == "DEBUG"
                assert "Error calculating message counts" in caplog.records[0].message
                assert "Connection failed" in caplog.records[0].message

    def test_calculate_message_counts_handles_redis_response_error(
        self, broker, caplog
    ):
        """Test that _calculate_message_counts handles Redis ResponseError properly"""
        # Create consumer groups and streams to track
        broker.get_next("test_stream", "test_group")
        broker.get_next("another_stream", "another_group")

        # Mock Redis llen to raise ResponseError for specific stream
        def mock_llen_side_effect(stream_name):
            if stream_name == "test_stream":
                raise redis.ResponseError("Stream might not exist")
            return 5  # Return count for other streams

        with patch.object(
            broker.redis_instance, "llen", side_effect=mock_llen_side_effect
        ):
            # Clear any existing logs
            caplog.clear()

            # Set log level to capture debug messages
            with caplog.at_level(logging.DEBUG):
                # Call _calculate_message_counts which should handle the ResponseError
                result = broker._calculate_message_counts()

                # Should return count for streams that worked (another_stream = 5)
                assert result == {"total_messages": 5}

                # Should not log any error messages since ResponseError is handled silently
                # (it just means the stream might not exist)
                assert len([r for r in caplog.records if r.levelname == "DEBUG"]) == 0


@pytest.mark.redis
class TestRedisMessageIdFormat:
    """Test Redis-specific message ID format and validation"""

    def test_message_id_format_validation(self, broker):
        """Test that Redis message IDs follow expected format"""
        # Publish a message and get its ID
        message_id = broker.publish("test_stream", {"data": "test"})

        # Redis message IDs should be strings
        assert isinstance(message_id, str)
        assert len(message_id) > 0

        # Should be able to retrieve the message using this ID
        retrieved = broker.get_next("test_stream", "test_group")
        assert retrieved is not None
        assert retrieved[0] == message_id

    def test_message_position_tracking(self, broker):
        """Test that message positions are correctly tracked per consumer group"""
        # Publish multiple messages
        id1 = broker.publish("test_stream", {"data": "msg1"})
        id2 = broker.publish("test_stream", {"data": "msg2"})
        broker.publish("test_stream", {"data": "msg3"})

        # Get messages with different consumer groups
        msg1_group1 = broker.get_next("test_stream", "group1")
        msg1_group2 = broker.get_next("test_stream", "group2")

        # Both groups should get the first message
        assert msg1_group1[0] == id1
        assert msg1_group2[0] == id1

        # Get next message for group1
        msg2_group1 = broker.get_next("test_stream", "group1")
        assert msg2_group1[0] == id2

        # Group2 should still get the second message when it asks
        msg2_group2 = broker.get_next("test_stream", "group2")
        assert msg2_group2[0] == id2


@pytest.mark.redis
class TestRedisAckNackLogging:
    """Test Redis-specific ACK/NACK logging behavior"""

    def test_ack_logs_warning_for_unsupported_operation(self, broker, caplog):
        """Test that _ack method logs warning for unsupported operation"""
        stream = "test_stream"
        consumer_group = "test_group"
        message_id = "test-message-id"

        # Clear any existing logs
        caplog.clear()

        # Set log level to capture warnings
        with caplog.at_level(logging.WARNING):
            # Call _ack directly to test the Redis-specific implementation
            result = broker._ack(stream, message_id, consumer_group)

            # Should return False for unsupported operation
            assert result is False

            # Should log warning about unsupported operation
            assert len(caplog.records) == 1
            assert caplog.records[0].levelname == "WARNING"
            assert "ACK not supported by RedisPubSubBroker" in caplog.records[0].message
            assert message_id in caplog.records[0].message

    def test_nack_logs_warning_for_unsupported_operation(self, broker, caplog):
        """Test that _nack method logs warning for unsupported operation"""
        stream = "test_stream"
        consumer_group = "test_group"
        message_id = "test-message-id"

        # Clear any existing logs
        caplog.clear()

        # Set log level to capture warnings
        with caplog.at_level(logging.WARNING):
            # Call _nack directly to test the Redis-specific implementation
            result = broker._nack(stream, message_id, consumer_group)

            # Should return False for unsupported operation
            assert result is False

            # Should log warning about unsupported operation
            assert len(caplog.records) == 1
            assert caplog.records[0].levelname == "WARNING"
            assert (
                "NACK not supported by RedisPubSubBroker" in caplog.records[0].message
            )
            assert message_id in caplog.records[0].message


@pytest.mark.redis
class TestRedisConsumerGroupHandling:
    """Test Redis-specific consumer group handling behavior"""

    def test_ensure_group_when_group_already_exists(self, broker):
        """Test _ensure_group when consumer group already exists"""
        stream = "test_stream"
        consumer_group = "test_group"

        # Create the consumer group for the first time
        broker._ensure_group(consumer_group, stream)

        # Get the original group info
        group_key = f"{stream}:{consumer_group}"
        original_group_info = broker._consumer_groups[group_key].copy()

        # Ensure the group again - should not create a new one
        broker._ensure_group(consumer_group, stream)

        # Should still be the same group info
        assert group_key in broker._consumer_groups
        assert broker._consumer_groups[group_key] == original_group_info

        # Should not have created duplicate groups
        assert len(broker._consumer_groups) == 1

    def test_info_method_aggregates_consumer_groups_across_streams(self, broker):
        """Test that _info method properly aggregates consumer groups across multiple streams"""
        # Create same consumer group name across different streams
        broker.get_next("stream1", "shared_group")
        broker.get_next("stream2", "shared_group")
        broker.get_next("stream1", "unique_group")

        # Get info
        info = broker._info()

        # Should have consumer groups section
        assert "consumer_groups" in info
        consumer_groups = info["consumer_groups"]

        # Should have both groups
        assert "shared_group" in consumer_groups
        assert "unique_group" in consumer_groups

        # Shared group should be aggregated (not duplicated)
        shared_group_info = consumer_groups["shared_group"]
        assert "consumers" in shared_group_info
        assert "created_at" in shared_group_info
        assert "consumer_count" in shared_group_info
        assert isinstance(shared_group_info["consumers"], list)
        assert isinstance(shared_group_info["created_at"], float)
        assert shared_group_info["consumer_count"] == 0  # No active consumers

        # Unique group should also be present
        unique_group_info = consumer_groups["unique_group"]
        assert "consumers" in unique_group_info
        assert "created_at" in unique_group_info
        assert "consumer_count" in unique_group_info
