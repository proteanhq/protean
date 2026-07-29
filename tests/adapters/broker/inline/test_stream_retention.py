"""Tests for the stream-retention trim() hook on the inline broker.

The inline broker has no persistent stream to bound, so trim() is a no-op that
returns 0 and leaves stored messages untouched. These tests also cover the
BaseBroker default (which the inline override shadows) by calling it directly.
"""

from protean.port.broker import BaseBroker


class TestInlineBrokerTrim:
    """InlineBroker.trim is a no-op that removes nothing."""

    def test_trim_returns_zero(self, broker):
        """trim() reports zero entries removed."""
        assert broker.trim("test_stream", 5) == 0

    def test_trim_removes_nothing(self, broker):
        """Published messages survive a trim regardless of the maxlen."""
        stream = "test_stream"
        for i in range(10):
            broker.publish(stream, {"n": i})

        removed = broker.trim(stream, 1)

        assert removed == 0
        # All ten messages are still stored; nothing was trimmed away.
        assert len(broker._messages[stream]) == 10

    def test_base_broker_trim_default_is_noop(self, broker):
        """The BaseBroker default trim() (shadowed by the inline override) returns 0.

        Calling the unbound base method exercises the port-level default that
        brokers without a persistent stream fall back to.
        """
        assert BaseBroker.trim(broker, "test_stream", 5) == 0
