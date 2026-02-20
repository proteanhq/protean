"""Tests for StreamSubscription priority lanes feature.

Verifies that when priority lanes are enabled, StreamSubscription:
- Reads from a primary stream (non-blocking) before a backfill stream (blocking).
- ACKs, NACKs, and DLQ messages on the correct stream.
- Falls back to standard single-stream behavior when lanes are disabled.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from protean.server.subscription.stream_subscription import StreamSubscription


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeHandler:
    """Minimal stand-in for an event/command handler."""

    __name__ = "FakeHandler"
    __module__ = "tests.priority"
    __qualname__ = "FakeHandler"


def _make_engine(priority_lanes_config=None, server_extras=None):
    """Build a mock engine with controllable config.

    Args:
        priority_lanes_config: dict merged into ``server.priority_lanes``.
        server_extras: dict merged into ``server`` level config.
    """
    server_config = {}
    if server_extras:
        server_config.update(server_extras)
    if priority_lanes_config is not None:
        server_config["priority_lanes"] = priority_lanes_config

    engine = MagicMock()
    engine.domain.config = {"server": server_config}
    engine.domain.brokers = {"default": MagicMock()}
    engine.shutting_down = False
    engine.emitter = MagicMock()
    engine.loop = asyncio.new_event_loop()
    return engine


def _make_subscription(engine, stream_category="orders", **kwargs):
    """Instantiate a StreamSubscription with the mock engine."""
    return StreamSubscription(
        engine=engine,
        stream_category=stream_category,
        handler=_FakeHandler,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Initialization Tests
# ---------------------------------------------------------------------------


class TestInitialization:
    """Tests for __init__ configuration of priority lanes."""

    def test_lanes_disabled_by_default(self):
        """No priority_lanes config -> _lanes_enabled is False."""
        engine = _make_engine()
        sub = _make_subscription(engine)

        assert sub._lanes_enabled is False

    def test_lanes_enabled_from_config(self):
        """Config with enabled=True -> _lanes_enabled is True."""
        engine = _make_engine(priority_lanes_config={"enabled": True})
        sub = _make_subscription(engine)

        assert sub._lanes_enabled is True

    def test_backfill_stream_name_default(self):
        """Default backfill suffix is 'backfill'."""
        engine = _make_engine(priority_lanes_config={"enabled": True})
        sub = _make_subscription(engine, stream_category="customer")

        assert sub._backfill_suffix == "backfill"
        assert sub.backfill_stream == "customer:backfill"

    def test_backfill_stream_name_custom_suffix(self):
        """Custom backfill_suffix is reflected in backfill_stream."""
        engine = _make_engine(
            priority_lanes_config={"enabled": True, "backfill_suffix": "migration"}
        )
        sub = _make_subscription(engine, stream_category="customer")

        assert sub._backfill_suffix == "migration"
        assert sub.backfill_stream == "customer:migration"

    @pytest.mark.asyncio
    async def test_initialize_creates_primary_consumer_group(self):
        """initialize() always creates a consumer group for the primary stream."""
        engine = _make_engine()
        sub = _make_subscription(engine, stream_category="orders")

        await sub.initialize()

        broker = engine.domain.brokers["default"]
        broker._ensure_group.assert_any_call(sub.consumer_group, "orders")

    @pytest.mark.asyncio
    async def test_initialize_creates_backfill_consumer_group_when_enabled(self):
        """initialize() creates a consumer group for the backfill stream when lanes are enabled."""
        engine = _make_engine(priority_lanes_config={"enabled": True})
        sub = _make_subscription(engine, stream_category="orders")

        await sub.initialize()

        broker = engine.domain.brokers["default"]
        # Primary group
        broker._ensure_group.assert_any_call(sub.consumer_group, "orders")
        # Backfill group
        broker._ensure_group.assert_any_call(sub.consumer_group, "orders:backfill")

    @pytest.mark.asyncio
    async def test_initialize_skips_backfill_group_when_disabled(self):
        """initialize() does NOT create a backfill consumer group when lanes are disabled."""
        engine = _make_engine()
        sub = _make_subscription(engine, stream_category="orders")

        await sub.initialize()

        broker = engine.domain.brokers["default"]
        # Only one call — the primary group
        assert broker._ensure_group.call_count == 1
        broker._ensure_group.assert_called_once_with(sub.consumer_group, "orders")


# ---------------------------------------------------------------------------
# Priority Reading Tests
# ---------------------------------------------------------------------------


class TestPriorityReading:
    """Tests for the two-lane reading behaviour inside poll()."""

    @pytest.mark.asyncio
    async def test_primary_has_messages_reads_primary_only(self):
        """When the primary stream has messages, the backfill stream is never read."""
        engine = _make_engine(priority_lanes_config={"enabled": True})
        sub = _make_subscription(engine, stream_category="orders")
        sub.broker = engine.domain.brokers["default"]

        primary_messages = [("msg-1", {"data": "a"})]

        # read_blocking returns messages for primary, should not be called for backfill
        call_count = 0

        def _read_blocking(stream, **kwargs):
            nonlocal call_count
            call_count += 1
            if stream == "orders":
                return primary_messages
            # Should never reach backfill
            return []

        sub.broker.read_blocking = MagicMock(side_effect=_read_blocking)

        # Run a single iteration of the poll loop then stop
        processed_batches = []

        async def _fake_process_batch(messages):
            processed_batches.append(messages)
            # Stop the loop after processing one batch
            sub.keep_going = False

        sub.process_batch = _fake_process_batch

        await sub.poll()

        # Only the primary stream was read
        assert call_count == 1
        sub.broker.read_blocking.assert_called_once()
        assert sub.broker.read_blocking.call_args.kwargs["stream"] == "orders"

    @pytest.mark.asyncio
    async def test_primary_empty_reads_backfill(self):
        """When the primary stream is empty, the backfill stream is read."""
        engine = _make_engine(priority_lanes_config={"enabled": True})
        sub = _make_subscription(engine, stream_category="orders")
        sub.broker = engine.domain.brokers["default"]

        backfill_messages = [("msg-bf-1", {"data": "b"})]
        streams_read = []

        def _read_blocking(stream, **kwargs):
            streams_read.append(stream)
            if stream == "orders":
                return []  # Primary empty
            if stream == "orders:backfill":
                return backfill_messages
            return []

        sub.broker.read_blocking = MagicMock(side_effect=_read_blocking)

        async def _fake_process_batch(messages):
            sub.keep_going = False

        sub.process_batch = _fake_process_batch

        await sub.poll()

        # Both streams were read: primary first, then backfill
        assert streams_read == ["orders", "orders:backfill"]

    @pytest.mark.asyncio
    async def test_primary_read_is_nonblocking(self):
        """The primary stream read uses timeout_ms=0 (non-blocking)."""
        engine = _make_engine(priority_lanes_config={"enabled": True})
        sub = _make_subscription(engine, stream_category="orders")
        sub.broker = engine.domain.brokers["default"]

        captured_kwargs = {}

        def _read_blocking(stream, **kwargs):
            if stream == "orders":
                captured_kwargs.update(kwargs)
                return [("msg-1", {"data": "a"})]
            return []

        sub.broker.read_blocking = MagicMock(side_effect=_read_blocking)

        async def _fake_process_batch(messages):
            sub.keep_going = False

        sub.process_batch = _fake_process_batch

        await sub.poll()

        assert captured_kwargs["timeout_ms"] == 0

    @pytest.mark.asyncio
    async def test_backfill_read_is_blocking_with_cap(self):
        """The backfill stream read uses min(configured_timeout, 1000)."""
        # Configure a large timeout (5000ms) so we can verify the cap
        engine = _make_engine(
            priority_lanes_config={"enabled": True},
            server_extras={"stream_subscription": {"blocking_timeout_ms": 5000}},
        )
        sub = _make_subscription(engine, stream_category="orders")
        sub.broker = engine.domain.brokers["default"]

        backfill_kwargs = {}

        def _read_blocking(stream, **kwargs):
            if stream == "orders":
                return []  # Primary empty
            if stream == "orders:backfill":
                backfill_kwargs.update(kwargs)
                return [("msg-bf-1", {"data": "b"})]
            return []

        sub.broker.read_blocking = MagicMock(side_effect=_read_blocking)

        async def _fake_process_batch(messages):
            sub.keep_going = False

        sub.process_batch = _fake_process_batch

        await sub.poll()

        # Backfill timeout should be capped at 1000 even though configured is 5000
        assert backfill_kwargs["timeout_ms"] == 1000

    @pytest.mark.asyncio
    async def test_backfill_read_uses_configured_timeout_when_under_cap(self):
        """When configured timeout < 1000, backfill uses the configured value."""
        engine = _make_engine(
            priority_lanes_config={"enabled": True},
            server_extras={"stream_subscription": {"blocking_timeout_ms": 500}},
        )
        sub = _make_subscription(engine, stream_category="orders")
        sub.broker = engine.domain.brokers["default"]

        backfill_kwargs = {}

        def _read_blocking(stream, **kwargs):
            if stream == "orders":
                return []
            if stream == "orders:backfill":
                backfill_kwargs.update(kwargs)
                return [("msg-bf-1", {"data": "b"})]
            return []

        sub.broker.read_blocking = MagicMock(side_effect=_read_blocking)

        async def _fake_process_batch(messages):
            sub.keep_going = False

        sub.process_batch = _fake_process_batch

        await sub.poll()

        assert backfill_kwargs["timeout_ms"] == 500


# ---------------------------------------------------------------------------
# ACK Handling Tests
# ---------------------------------------------------------------------------


class TestACKHandling:
    """Tests for ACK / NACK / DLQ routing based on _active_stream."""

    @pytest.mark.asyncio
    async def test_ack_primary_message_uses_primary_stream(self):
        """ACK is sent to stream_category when processing primary messages."""
        engine = _make_engine(priority_lanes_config={"enabled": True})
        sub = _make_subscription(engine, stream_category="orders")
        sub.broker = engine.domain.brokers["default"]
        sub.broker.ack = MagicMock(return_value=True)

        # Simulate active stream pointing to primary
        sub._active_stream = sub.stream_category

        result = await sub._acknowledge_message("msg-1")

        sub.broker.ack.assert_called_once_with("orders", "msg-1", sub.consumer_group)
        assert result is True

    @pytest.mark.asyncio
    async def test_ack_backfill_message_uses_backfill_stream(self):
        """ACK is sent to backfill_stream when processing backfill messages."""
        engine = _make_engine(priority_lanes_config={"enabled": True})
        sub = _make_subscription(engine, stream_category="orders")
        sub.broker = engine.domain.brokers["default"]
        sub.broker.ack = MagicMock(return_value=True)

        # Simulate active stream pointing to backfill
        sub._active_stream = sub.backfill_stream

        result = await sub._acknowledge_message("msg-bf-1")

        sub.broker.ack.assert_called_once_with(
            "orders:backfill", "msg-bf-1", sub.consumer_group
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_nack_primary_message_uses_primary_stream(self):
        """NACK is sent to stream_category when retrying a primary message."""
        engine = _make_engine(priority_lanes_config={"enabled": True})
        sub = _make_subscription(engine, stream_category="orders")
        sub.broker = engine.domain.brokers["default"]

        sub._active_stream = sub.stream_category

        # Use zero delay for test speed
        sub.retry_delay_seconds = 0

        await sub._retry_message("msg-1", retry_count=1)

        sub.broker.nack.assert_called_once_with("orders", "msg-1", sub.consumer_group)

    @pytest.mark.asyncio
    async def test_nack_backfill_message_uses_backfill_stream(self):
        """NACK is sent to backfill_stream when retrying a backfill message."""
        engine = _make_engine(priority_lanes_config={"enabled": True})
        sub = _make_subscription(engine, stream_category="orders")
        sub.broker = engine.domain.brokers["default"]

        sub._active_stream = sub.backfill_stream
        sub.retry_delay_seconds = 0

        await sub._retry_message("msg-bf-1", retry_count=1)

        sub.broker.nack.assert_called_once_with(
            "orders:backfill", "msg-bf-1", sub.consumer_group
        )

    @pytest.mark.asyncio
    async def test_dlq_for_primary_uses_primary_dlq(self):
        """DLQ publish targets stream_category:dlq for primary messages."""
        engine = _make_engine(priority_lanes_config={"enabled": True})
        sub = _make_subscription(engine, stream_category="orders")
        sub.broker = engine.domain.brokers["default"]

        sub._active_stream = sub.stream_category

        await sub.move_to_dlq("msg-1", {"data": "fail"})

        # Publish should target the primary DLQ stream
        sub.broker.publish.assert_called_once()
        target_stream = sub.broker.publish.call_args[0][0]
        assert target_stream == "orders:dlq"

    @pytest.mark.asyncio
    async def test_dlq_for_backfill_uses_backfill_dlq(self):
        """DLQ publish targets stream_category:backfill:dlq for backfill messages."""
        engine = _make_engine(priority_lanes_config={"enabled": True})
        sub = _make_subscription(engine, stream_category="orders")
        sub.broker = engine.domain.brokers["default"]

        sub._active_stream = sub.backfill_stream

        await sub.move_to_dlq("msg-bf-1", {"data": "fail"})

        sub.broker.publish.assert_called_once()
        target_stream = sub.broker.publish.call_args[0][0]
        assert target_stream == "orders:backfill:dlq"


# ---------------------------------------------------------------------------
# Standard Mode Tests
# ---------------------------------------------------------------------------


class TestStandardMode:
    """Tests that standard (non-lanes) mode behaviour is unchanged."""

    @pytest.mark.asyncio
    async def test_standard_mode_unchanged(self):
        """When lanes are disabled, poll() uses the original blocking read path."""
        engine = _make_engine()  # No priority_lanes config
        sub = _make_subscription(engine, stream_category="orders")
        sub.broker = engine.domain.brokers["default"]

        standard_messages = [("msg-1", {"data": "a"})]

        def _read_blocking(stream, **kwargs):
            return standard_messages

        sub.broker.read_blocking = MagicMock(side_effect=_read_blocking)

        processed = []

        async def _fake_process_batch(messages):
            processed.append(messages)
            sub.keep_going = False

        sub.process_batch = _fake_process_batch

        await sub.poll()

        # Should use get_next_batch_of_messages which calls read_blocking
        # with the configured timeout (not 0)
        sub.broker.read_blocking.assert_called_once()
        call_kwargs = sub.broker.read_blocking.call_args.kwargs
        assert call_kwargs["stream"] == "orders"
        assert call_kwargs["timeout_ms"] == sub.blocking_timeout_ms
        assert call_kwargs["timeout_ms"] != 0  # NOT non-blocking

        # Messages were processed
        assert len(processed) == 1
        assert processed[0] == standard_messages

    @pytest.mark.asyncio
    async def test_standard_mode_active_stream_is_primary(self):
        """In standard mode, _active_stream always points to the primary stream."""
        engine = _make_engine()
        sub = _make_subscription(engine, stream_category="orders")
        sub.broker = engine.domain.brokers["default"]

        active_streams_seen = []

        def _read_blocking(stream, **kwargs):
            active_streams_seen.append(sub._active_stream)
            return [("msg-1", {"data": "a"})]

        sub.broker.read_blocking = MagicMock(side_effect=_read_blocking)

        async def _fake_process_batch(messages):
            active_streams_seen.append(sub._active_stream)
            sub.keep_going = False

        sub.process_batch = _fake_process_batch

        await sub.poll()

        # _active_stream should always be the primary stream
        for stream in active_streams_seen:
            assert stream == "orders"


# ---------------------------------------------------------------------------
# Error Handling Tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for graceful degradation when Redis read calls fail."""

    @pytest.mark.asyncio
    async def test_primary_read_error_falls_through_to_backfill(self):
        """When primary non-blocking read raises, we still try backfill."""
        engine = _make_engine(priority_lanes_config={"enabled": True})
        sub = _make_subscription(engine, stream_category="orders")
        sub.broker = engine.domain.brokers["default"]

        backfill_messages = [("msg-bf-1", {"data": "b"})]
        streams_read = []

        def _read_blocking(stream, **kwargs):
            streams_read.append(stream)
            if stream == "orders":
                raise ConnectionError("Redis connection lost")
            return backfill_messages

        sub.broker.read_blocking = MagicMock(side_effect=_read_blocking)

        async def _fake_process_batch(messages):
            sub.keep_going = False

        sub.process_batch = _fake_process_batch

        await sub.poll()

        # Primary failed, but backfill should still be read
        assert "orders" in streams_read
        assert "orders:backfill" in streams_read

    @pytest.mark.asyncio
    async def test_backfill_read_error_loops_back_to_primary(self):
        """When backfill blocking read raises, the loop continues to primary."""
        engine = _make_engine(priority_lanes_config={"enabled": True})
        sub = _make_subscription(engine, stream_category="orders")
        sub.broker = engine.domain.brokers["default"]

        iteration = 0
        streams_read = []

        def _read_blocking(stream, **kwargs):
            nonlocal iteration
            streams_read.append(stream)
            if stream == "orders":
                if iteration > 0:
                    # On second primary read, return messages to break the loop
                    return [("msg-1", {"data": "a"})]
                return []  # Primary empty on first pass
            if stream == "orders:backfill":
                iteration += 1
                raise ConnectionError("Redis connection lost on backfill")
            return []

        sub.broker.read_blocking = MagicMock(side_effect=_read_blocking)

        async def _fake_process_batch(messages):
            sub.keep_going = False

        sub.process_batch = _fake_process_batch

        await sub.poll()

        # Should read primary, then backfill (error), then primary again
        assert streams_read[0] == "orders"
        assert streams_read[1] == "orders:backfill"
        assert streams_read[2] == "orders"

    @pytest.mark.asyncio
    async def test_both_streams_error_continues_loop(self):
        """When both primary and backfill raise, the loop retries."""
        engine = _make_engine(priority_lanes_config={"enabled": True})
        sub = _make_subscription(engine, stream_category="orders")
        sub.broker = engine.domain.brokers["default"]

        call_count = 0

        def _read_blocking(stream, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > 3:
                # Break out by stopping the loop
                sub.keep_going = False
                return []
            raise ConnectionError("Redis down")

        sub.broker.read_blocking = MagicMock(side_effect=_read_blocking)
        sub.process_batch = MagicMock()

        await sub.poll()

        # Should have attempted reads before giving up
        assert call_count > 2

    @pytest.mark.asyncio
    async def test_active_stream_reset_after_backfill_batch_error(self):
        """After a backfill process_batch error, next iteration checks primary first."""
        engine = _make_engine(priority_lanes_config={"enabled": True})
        sub = _make_subscription(engine, stream_category="orders")
        sub.broker = engine.domain.brokers["default"]

        iteration = 0
        active_at_read_time = []

        def _read_blocking(stream, **kwargs):
            nonlocal iteration
            active_at_read_time.append(sub._active_stream)
            if stream == "orders":
                if iteration > 0:
                    # Second primary check: return messages to end the loop
                    return [("msg-1", {"data": "a"})]
                return []  # Primary empty first time
            if stream == "orders:backfill":
                iteration += 1
                return [("msg-bf-1", {"data": "b"})]
            return []

        sub.broker.read_blocking = MagicMock(side_effect=_read_blocking)

        batch_count = 0

        async def _fake_process_batch(messages):
            nonlocal batch_count
            batch_count += 1
            if batch_count == 1:
                # First batch (backfill) raises an error
                raise RuntimeError("Handler failed")
            # Second batch (primary) succeeds
            sub.keep_going = False

        sub.process_batch = _fake_process_batch

        await sub.poll()

        # After backfill error, _active_stream should be reset to primary
        # The third read should be on the primary stream
        assert active_at_read_time[0] == "orders"  # First primary check
        assert active_at_read_time[1] == "orders:backfill"  # Backfill read
        assert active_at_read_time[2] == "orders"  # Re-check primary


# ---------------------------------------------------------------------------
# DLQ Metadata Tests
# ---------------------------------------------------------------------------


class TestDLQMetadata:
    """Tests for DLQ message metadata correctness."""

    @pytest.mark.asyncio
    async def test_backfill_dlq_metadata_includes_backfill_stream(self):
        """DLQ message metadata correctly records backfill as the original stream."""
        engine = _make_engine(priority_lanes_config={"enabled": True})
        sub = _make_subscription(engine, stream_category="orders")
        sub.broker = engine.domain.brokers["default"]

        # Simulate processing a backfill message
        sub._active_stream = sub.backfill_stream

        captured_payloads = []
        sub.broker.publish = MagicMock(
            side_effect=lambda stream, payload: captured_payloads.append(
                (stream, payload)
            )
        )

        await sub.move_to_dlq("msg-bf-1", {"data": "failed"})

        assert len(captured_payloads) == 1
        dlq_stream, dlq_payload = captured_payloads[0]

        assert dlq_stream == "orders:backfill:dlq"
        assert dlq_payload["_dlq_metadata"]["original_stream"] == "orders:backfill"
        assert dlq_payload["_dlq_metadata"]["original_id"] == "msg-bf-1"

    @pytest.mark.asyncio
    async def test_primary_dlq_metadata_includes_primary_stream(self):
        """DLQ message metadata correctly records primary as the original stream."""
        engine = _make_engine(priority_lanes_config={"enabled": True})
        sub = _make_subscription(engine, stream_category="orders")
        sub.broker = engine.domain.brokers["default"]

        sub._active_stream = sub.stream_category

        captured_payloads = []
        sub.broker.publish = MagicMock(
            side_effect=lambda stream, payload: captured_payloads.append(
                (stream, payload)
            )
        )

        await sub.move_to_dlq("msg-1", {"data": "failed"})

        assert len(captured_payloads) == 1
        dlq_stream, dlq_payload = captured_payloads[0]

        assert dlq_stream == "orders:dlq"
        assert dlq_payload["_dlq_metadata"]["original_stream"] == "orders"


# ---------------------------------------------------------------------------
# Multiple Subscription Tests
# ---------------------------------------------------------------------------


class TestMultipleSubscriptions:
    """Tests for multiple subscriptions on the same stream with priority lanes."""

    @pytest.mark.asyncio
    async def test_two_subscriptions_same_stream_independent_groups(self):
        """Two subscriptions on the same stream have independent consumer groups."""
        engine = _make_engine(priority_lanes_config={"enabled": True})

        class _HandlerA:
            __name__ = "HandlerA"
            __module__ = "tests.priority"
            __qualname__ = "HandlerA"

        class _HandlerB:
            __name__ = "HandlerB"
            __module__ = "tests.priority"
            __qualname__ = "HandlerB"

        sub_a = StreamSubscription(
            engine=engine,
            stream_category="customer",
            handler=_HandlerA,
        )
        sub_b = StreamSubscription(
            engine=engine,
            stream_category="customer",
            handler=_HandlerB,
        )

        # Both should have lanes enabled and the same stream names
        assert sub_a._lanes_enabled is True
        assert sub_b._lanes_enabled is True
        assert sub_a.backfill_stream == "customer:backfill"
        assert sub_b.backfill_stream == "customer:backfill"

        # But different consumer groups
        assert sub_a.consumer_group != sub_b.consumer_group

    @pytest.mark.asyncio
    async def test_two_subscriptions_initialize_both_create_groups(self):
        """Both subscriptions create consumer groups for primary and backfill."""
        engine = _make_engine(priority_lanes_config={"enabled": True})

        class _HandlerA:
            __name__ = "HandlerA"
            __module__ = "tests.priority"
            __qualname__ = "HandlerA"

        class _HandlerB:
            __name__ = "HandlerB"
            __module__ = "tests.priority"
            __qualname__ = "HandlerB"

        sub_a = StreamSubscription(
            engine=engine,
            stream_category="customer",
            handler=_HandlerA,
        )
        sub_b = StreamSubscription(
            engine=engine,
            stream_category="customer",
            handler=_HandlerB,
        )

        broker = engine.domain.brokers["default"]

        await sub_a.initialize()
        await sub_b.initialize()

        # Each subscription should have created groups for both streams
        # That's 4 calls total: 2 handlers x 2 streams (primary + backfill)
        assert broker._ensure_group.call_count == 4
