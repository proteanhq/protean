"""Tests for Redis broker DLQ trim and depth methods."""

import time

import pytest

from tests.shared import REDIS_URI


@pytest.mark.redis
class TestRedisDLQTrimAndDepth:
    """Redis broker dlq_trim and dlq_depth integration tests."""

    def test_dlq_trim_removes_old_entries(self, test_domain):
        """dlq_trim removes entries older than min_id."""
        broker = test_domain.brokers["default"]

        dlq_stream = "test-dlq-trim:dlq"
        try:
            broker.redis_instance.xadd(dlq_stream, {"data": "old1"})
            broker.redis_instance.xadd(dlq_stream, {"data": "old2"})
            time.sleep(0.01)
            min_id = f"{int(time.time() * 1000)}-0"
            broker.redis_instance.xadd(dlq_stream, {"data": "new1"})

            trimmed = broker.dlq_trim(dlq_stream, min_id)
            assert trimmed >= 2

            remaining = broker.dlq_depth(dlq_stream)
            assert remaining >= 1
        finally:
            broker.redis_instance.delete(dlq_stream)

    def test_dlq_depth_returns_stream_length(self, test_domain):
        """dlq_depth returns the number of entries in a DLQ stream."""
        broker = test_domain.brokers["default"]

        dlq_stream = "test-dlq-depth:dlq"
        try:
            assert broker.dlq_depth(dlq_stream) == 0

            broker.redis_instance.xadd(dlq_stream, {"data": "msg1"})
            broker.redis_instance.xadd(dlq_stream, {"data": "msg2"})

            assert broker.dlq_depth(dlq_stream) == 2
        finally:
            broker.redis_instance.delete(dlq_stream)

    def test_dlq_trim_nonexistent_stream(self, test_domain):
        """dlq_trim returns 0 for a stream that doesn't exist."""
        broker = test_domain.brokers["default"]
        result = broker.dlq_trim("nonexistent:dlq", "999999999999-0")
        assert result == 0

    def test_dlq_depth_nonexistent_stream(self, test_domain):
        """dlq_depth returns 0 for a stream that doesn't exist."""
        broker = test_domain.brokers["default"]
        result = broker.dlq_depth("nonexistent:dlq")
        assert result == 0
