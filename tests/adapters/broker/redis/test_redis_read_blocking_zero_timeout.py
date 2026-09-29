"""Live Redis tests for read_blocking timeouts.

A zero timeout must return at once and must not send ``BLOCK 0``, which
Redis reads as "wait forever" and which would hang the call until the client's
socket timeout, logging ``broker.redis.read_blocking_failed``.
"""

import logging
import time
from uuid import uuid4

import pytest


def _fresh_stream():
    return f"zero-timeout-{uuid4().hex}"


@pytest.mark.redis
class TestReadBlockingTimeoutAgainstRedis:
    def test_zero_timeout_returns_immediately_on_empty_stream(
        self, test_domain, caplog
    ):
        broker = test_domain.brokers["default"]

        with caplog.at_level(logging.DEBUG):
            started = time.monotonic()
            result = broker.read_blocking(
                stream=_fresh_stream(),
                consumer_group="zero-timeout-group",
                consumer_name="zero-timeout-consumer",
                timeout_ms=0,
            )
            elapsed = time.monotonic() - started

        assert result == []
        assert elapsed < 0.5
        assert "broker.redis.read_blocking_failed" not in caplog.text

    def test_zero_timeout_returns_published_message(self, test_domain):
        broker = test_domain.brokers["default"]
        stream = _fresh_stream()
        broker.publish(stream, {"foo": "bar"})

        result = broker.read_blocking(
            stream=stream,
            consumer_group="zero-timeout-group",
            consumer_name="zero-timeout-consumer",
            timeout_ms=0,
        )

        assert len(result) == 1
        assert result[0][1]["foo"] == "bar"

    def test_positive_timeout_waits_then_returns_empty(self, test_domain):
        broker = test_domain.brokers["default"]

        started = time.monotonic()
        result = broker.read_blocking(
            stream=_fresh_stream(),
            consumer_group="positive-timeout-group",
            consumer_name="positive-timeout-consumer",
            timeout_ms=200,
        )
        elapsed = time.monotonic() - started

        assert result == []
        assert 0.15 <= elapsed < 1.0
