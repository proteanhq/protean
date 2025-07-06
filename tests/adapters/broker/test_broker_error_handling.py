"""Test cases for broker error handling scenarios to ensure code coverage"""

from unittest.mock import Mock, patch

import pytest

from protean.adapters.broker.inline import InlineBroker
from protean.core.subscriber import BaseSubscriber


class DummySubscriber(BaseSubscriber):
    """Test subscriber for sync processing tests"""

    def __call__(self, message):
        pass


class TestBrokerErrorHandling:
    """Test error handling paths in broker methods"""

    def test_publish_connection_error_with_successful_recovery(self, test_domain):
        """Test publish method when connection error occurs but recovery succeeds"""
        broker = InlineBroker("test_broker", test_domain, {})

        # Mock _publish to raise connection error on first call, succeed on second
        call_count = 0

        def mock_publish(stream, message):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Connection timeout")
            return "test_id"

        with patch.object(broker, "_publish", side_effect=mock_publish):
            with patch.object(broker, "_ensure_connection", return_value=True):
                with patch.object(broker, "_is_connection_error", return_value=True):
                    # This should cover line 119 (connection error check)
                    identifier = broker.publish("test_stream", {"data": "test"})

                    assert identifier == "test_id"
                    assert call_count == 2  # Called twice due to retry

    def test_publish_connection_error_with_failed_recovery(self, test_domain):
        """Test publish method when connection error occurs and recovery fails"""
        broker = InlineBroker("test_broker", test_domain, {})

        with patch.object(
            broker, "_publish", side_effect=Exception("Connection timeout")
        ):
            with patch.object(broker, "_ensure_connection", return_value=False):
                with patch.object(broker, "_is_connection_error", return_value=True):
                    # This should cover line 119 (connection error check)
                    with pytest.raises(Exception, match="Connection timeout"):
                        broker.publish("test_stream", {"data": "test"})

    def test_publish_non_connection_error(self, test_domain):
        """Test publish method when non-connection error occurs"""
        broker = InlineBroker("test_broker", test_domain, {})

        with patch.object(
            broker, "_publish", side_effect=Exception("Non-connection error")
        ):
            with patch.object(broker, "_is_connection_error", return_value=False):
                # This should cover line 130 (else clause for non-connection errors)
                with pytest.raises(Exception, match="Non-connection error"):
                    broker.publish("test_stream", {"data": "test"})

    def test_health_stats_exception_handling(self, test_domain):
        """Test health_stats method when exception occurs"""
        broker = InlineBroker("test_broker", test_domain, {})

        with patch.object(
            broker, "_health_stats", side_effect=Exception("Health check failed")
        ):
            with patch.object(broker, "ping", side_effect=Exception("Ping failed")):
                # This should cover lines 231-233 (exception handling in health_stats)
                stats = broker.health_stats()

                assert stats["status"] == "unhealthy"
                assert stats["connected"] is False
                assert stats["last_ping_ms"] is None
                assert stats["uptime_seconds"] == 0
                assert "error" in stats["details"]

    def test_get_next_connection_error_with_successful_recovery(self, test_domain):
        """Test get_next method when connection error occurs but recovery succeeds"""
        broker = InlineBroker("test_broker", test_domain, {})

        # Mock _get_next to raise connection error on first call, succeed on second
        call_count = 0

        def mock_get_next(stream, consumer_group):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Connection timeout")
            return {"data": "test"}

        with patch.object(broker, "_get_next", side_effect=mock_get_next):
            with patch.object(broker, "_ensure_connection", return_value=True):
                with patch.object(broker, "_is_connection_error", return_value=True):
                    # This should cover lines 330-331 (connection error check in get_next)
                    message = broker.get_next("test_stream", "test_group")

                    assert message == {"data": "test"}
                    assert call_count == 2  # Called twice due to retry

    def test_get_next_connection_error_with_failed_recovery(self, test_domain):
        """Test get_next method when connection error occurs and recovery fails"""
        broker = InlineBroker("test_broker", test_domain, {})

        with patch.object(
            broker, "_get_next", side_effect=Exception("Connection timeout")
        ):
            with patch.object(broker, "_ensure_connection", return_value=False):
                with patch.object(broker, "_is_connection_error", return_value=True):
                    # This should cover lines 330-331 (connection error check in get_next)
                    with pytest.raises(Exception, match="Connection timeout"):
                        broker.get_next("test_stream", "test_group")

    def test_get_next_non_connection_error(self, test_domain):
        """Test get_next method when non-connection error occurs"""
        broker = InlineBroker("test_broker", test_domain, {})

        with patch.object(
            broker, "_get_next", side_effect=Exception("Non-connection error")
        ):
            with patch.object(broker, "_is_connection_error", return_value=False):
                # This should cover the else clause for non-connection errors in get_next
                with pytest.raises(Exception, match="Non-connection error"):
                    broker.get_next("test_stream", "test_group")

    def test_read_connection_error_with_successful_recovery(self, test_domain):
        """Test read method when connection error occurs but recovery succeeds"""
        broker = InlineBroker("test_broker", test_domain, {})

        # Mock _read to raise connection error on first call, succeed on second
        call_count = 0

        def mock_read(stream, consumer_group, no_of_messages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Connection timeout")
            return [("id1", {"data": "test"})]

        with patch.object(broker, "_read", side_effect=mock_read):
            with patch.object(broker, "_ensure_connection", return_value=True):
                with patch.object(broker, "_is_connection_error", return_value=True):
                    # This should cover lines 366-367 (connection error check in read)
                    messages = broker.read("test_stream", "test_group", 1)

                    assert messages == [("id1", {"data": "test"})]
                    assert call_count == 2  # Called twice due to retry

    def test_read_connection_error_with_failed_recovery(self, test_domain):
        """Test read method when connection error occurs and recovery fails"""
        broker = InlineBroker("test_broker", test_domain, {})

        with patch.object(broker, "_read", side_effect=Exception("Connection timeout")):
            with patch.object(broker, "_ensure_connection", return_value=False):
                with patch.object(broker, "_is_connection_error", return_value=True):
                    # This should cover lines 366-367 (connection error check in read)
                    with pytest.raises(Exception, match="Connection timeout"):
                        broker.read("test_stream", "test_group", 1)

    def test_read_non_connection_error(self, test_domain):
        """Test read method when non-connection error occurs"""
        broker = InlineBroker("test_broker", test_domain, {})

        with patch.object(
            broker, "_read", side_effect=Exception("Non-connection error")
        ):
            with patch.object(broker, "_is_connection_error", return_value=False):
                # This should cover the else clause for non-connection errors in read
                with pytest.raises(Exception, match="Non-connection error"):
                    broker.read("test_stream", "test_group", 1)

    def test_ack_connection_error_with_successful_recovery(self, test_domain):
        """Test ack method when connection error occurs but recovery succeeds"""
        broker = InlineBroker("test_broker", test_domain, {})

        # Mock _ack to raise connection error on first call, succeed on second
        call_count = 0

        def mock_ack(stream, identifier, consumer_group):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Connection timeout")
            return True

        with patch.object(broker, "_ack", side_effect=mock_ack):
            with patch.object(broker, "_ensure_connection", return_value=True):
                with patch.object(broker, "_is_connection_error", return_value=True):
                    # This should cover lines 371-381 (connection error check in ack)
                    result = broker.ack("test_stream", "test_id", "test_group")

                    assert result is True
                    assert call_count == 2  # Called twice due to retry

    def test_ack_connection_error_with_failed_recovery(self, test_domain):
        """Test ack method when connection error occurs and recovery fails"""
        broker = InlineBroker("test_broker", test_domain, {})

        with patch.object(broker, "_ack", side_effect=Exception("Connection timeout")):
            with patch.object(broker, "_ensure_connection", return_value=False):
                with patch.object(broker, "_is_connection_error", return_value=True):
                    # This should cover lines 371-381 (connection error check in ack)
                    with pytest.raises(Exception, match="Connection timeout"):
                        broker.ack("test_stream", "test_id", "test_group")

    def test_ack_non_connection_error(self, test_domain):
        """Test ack method when non-connection error occurs"""
        broker = InlineBroker("test_broker", test_domain, {})

        with patch.object(
            broker, "_ack", side_effect=Exception("Non-connection error")
        ):
            with patch.object(broker, "_is_connection_error", return_value=False):
                # This should cover the else clause for non-connection errors in ack
                with pytest.raises(Exception, match="Non-connection error"):
                    broker.ack("test_stream", "test_id", "test_group")

    def test_nack_connection_error_with_successful_recovery(self, test_domain):
        """Test nack method when connection error occurs but recovery succeeds"""
        broker = InlineBroker("test_broker", test_domain, {})

        # Mock _nack to raise connection error on first call, succeed on second
        call_count = 0

        def mock_nack(stream, identifier, consumer_group):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Connection timeout")
            return True

        with patch.object(broker, "_nack", side_effect=mock_nack):
            with patch.object(broker, "_ensure_connection", return_value=True):
                with patch.object(broker, "_is_connection_error", return_value=True):
                    # This should cover lines 403-413 (connection error check in nack)
                    result = broker.nack("test_stream", "test_id", "test_group")

                    assert result is True
                    assert call_count == 2  # Called twice due to retry

    def test_nack_connection_error_with_failed_recovery(self, test_domain):
        """Test nack method when connection error occurs and recovery fails"""
        broker = InlineBroker("test_broker", test_domain, {})

        with patch.object(broker, "_nack", side_effect=Exception("Connection timeout")):
            with patch.object(broker, "_ensure_connection", return_value=False):
                with patch.object(broker, "_is_connection_error", return_value=True):
                    # This should cover lines 403-413 (connection error check in nack)
                    with pytest.raises(Exception, match="Connection timeout"):
                        broker.nack("test_stream", "test_id", "test_group")

    def test_nack_non_connection_error(self, test_domain):
        """Test nack method when non-connection error occurs"""
        broker = InlineBroker("test_broker", test_domain, {})

        with patch.object(
            broker, "_nack", side_effect=Exception("Non-connection error")
        ):
            with patch.object(broker, "_is_connection_error", return_value=False):
                # This should cover lines 435-445 (else clause for non-connection errors in nack)
                with pytest.raises(Exception, match="Non-connection error"):
                    broker.nack("test_stream", "test_id", "test_group")

    def test_publish_with_sync_processing_and_subscribers(self, test_domain):
        """Test publish method with sync processing and registered subscribers"""
        broker = InlineBroker("test_broker", test_domain, {})

        # Set up sync processing
        test_domain.config["message_processing"] = "sync"

        # Create and register a subscriber
        subscriber_instance = Mock()
        subscriber_class = Mock()
        subscriber_class.return_value = subscriber_instance
        subscriber_class.__name__ = "TestSubscriber"
        subscriber_class.meta_ = Mock()
        subscriber_class.meta_.stream = "test_stream"

        # Register subscriber
        broker.register(subscriber_class)

        # Mock _publish to return identifier
        with patch.object(broker, "_publish", return_value="test_id"):
            identifier = broker.publish("test_stream", {"data": "test"})

            assert identifier == "test_id"
            # Verify subscriber was called
            subscriber_class.assert_called_once()
            subscriber_instance.assert_called_once_with({"data": "test"})

    def test_get_next_with_unsupported_capability(self, test_domain):
        """Test get_next method when broker doesn't support consumer groups"""
        broker = InlineBroker("test_broker", test_domain, {})

        # Mock has_capability to return False for CONSUMER_GROUPS
        with patch.object(broker, "has_capability", return_value=False):
            result = broker.get_next("test_stream", "test_group")

            assert result is None

    def test_read_with_unsupported_capability(self, test_domain):
        """Test read method when broker doesn't support consumer groups"""
        broker = InlineBroker("test_broker", test_domain, {})

        # Mock has_capability to return False for CONSUMER_GROUPS
        with patch.object(broker, "has_capability", return_value=False):
            result = broker.read("test_stream", "test_group", 5)

            assert result == []

    def test_ack_with_unsupported_capability(self, test_domain):
        """Test ack method when broker doesn't support ack/nack"""
        broker = InlineBroker("test_broker", test_domain, {})

        # Mock has_capability to return False for ACK_NACK
        with patch.object(broker, "has_capability", return_value=False):
            result = broker.ack("test_stream", "test_id", "test_group")

            assert result is False

    def test_nack_with_unsupported_capability(self, test_domain):
        """Test nack method when broker doesn't support ack/nack"""
        broker = InlineBroker("test_broker", test_domain, {})

        # Mock has_capability to return False for ACK_NACK
        with patch.object(broker, "has_capability", return_value=False):
            result = broker.nack("test_stream", "test_id", "test_group")

            assert result is False

    def test_health_stats_with_degraded_status(self, test_domain):
        """Test health_stats method when broker is connected but has issues"""
        broker = InlineBroker("test_broker", test_domain, {})

        # Mock ping to succeed but _health_stats to report unhealthy
        with patch.object(broker, "ping", return_value=True):
            with patch.object(broker, "_health_stats", return_value={"healthy": False}):
                stats = broker.health_stats()

                assert stats["status"] == "degraded"
                assert stats["connected"] is True
                assert stats["details"]["healthy"] is False

    def test_health_stats_with_ping_success_but_no_ping_time(self, test_domain):
        """Test health_stats method when ping succeeds but no timing info"""
        broker = InlineBroker("test_broker", test_domain, {})

        # Reset ping time to None
        broker._last_ping_time = None

        with patch.object(broker, "ping", return_value=True):
            stats = broker.health_stats()

            assert stats["status"] == "healthy"
            assert stats["connected"] is True
            assert stats["last_ping_ms"] is None

    def test_publish_with_async_processing_no_subscribers(self, test_domain):
        """Test publish method with async processing (no immediate subscriber execution)"""
        broker = InlineBroker("test_broker", test_domain, {})

        # Set up async processing (default)
        test_domain.config["message_processing"] = "async"

        # Mock _publish to return identifier
        with patch.object(broker, "_publish", return_value="test_id"):
            identifier = broker.publish("test_stream", {"data": "test"})

            assert identifier == "test_id"
            # Should not execute subscribers in async mode

    def test_ping_exception_handling(self, test_domain):
        """Test ping method exception handling"""
        broker = InlineBroker("test_broker", test_domain, {})

        with patch.object(broker, "_ping", side_effect=Exception("Ping failed")):
            result = broker.ping()

            assert result is False
            assert broker._last_ping_time is None
            assert broker._last_ping_success is False

    def test_is_connection_error_detection(self, test_domain):
        """Test _is_connection_error method for different error types"""
        broker = InlineBroker("test_broker", test_domain, {})

        # Test connection-related errors
        connection_errors = [
            Exception("Connection timeout"),
            Exception("Connection refused"),
            Exception("Network unreachable"),
            Exception("Timed out"),
            Exception("Socket error"),
            Exception("Broken pipe"),
            Exception("Connection reset"),
        ]

        for error in connection_errors:
            assert broker._is_connection_error(error) is True

        # Test non-connection errors
        non_connection_errors = [
            Exception("Authentication failed"),
            Exception("Permission denied"),
            Exception("Invalid format"),
            Exception("Something else"),
        ]

        for error in non_connection_errors:
            assert broker._is_connection_error(error) is False
