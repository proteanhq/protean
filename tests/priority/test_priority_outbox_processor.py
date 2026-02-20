"""Tests for OutboxProcessor priority lane routing.

These tests verify that the OutboxProcessor correctly routes messages to
primary or backfill lanes based on message priority and configuration.
"""

import pytest
from unittest.mock import Mock

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.domain import Domain
from protean.fields import Integer, String
from protean.server.outbox_processor import OutboxProcessor
from protean.utils.eventing import Metadata, MessageHeaders, DomainMeta
from protean.utils.outbox import Outbox


class MockEngine:
    """Simple mock engine that provides only the necessary interface for testing."""

    def __init__(self, domain):
        self.domain = domain
        self.loop = None
        self.emitter = Mock()


class DummyAggregate(BaseAggregate):
    """Test aggregate for outbox testing."""

    name: String(max_length=50, required=True)
    count: Integer(default=0)


class DummyEvent(BaseEvent):
    """Test event for outbox testing."""

    aggregate_id: String(required=True)
    name: String(required=True)
    count: Integer(required=True)


def _make_metadata(msg_id, stream_category="customer"):
    """Helper to build a Metadata object with a known stream_category."""
    headers = MessageHeaders(id=msg_id, type="DummyEvent", stream="test-stream")
    domain_meta = DomainMeta(stream_category=stream_category)
    return Metadata(headers=headers, domain=domain_meta)


def _create_outbox_message(msg_id, priority=0, stream_category="customer"):
    """Helper to create an Outbox message with a given priority and stream_category."""
    return Outbox.create_message(
        message_id=msg_id,
        stream_name="test-stream",
        message_type="DummyEvent",
        data={"name": f"Test {msg_id}", "count": 1},
        metadata=_make_metadata(msg_id, stream_category),
        priority=priority,
        correlation_id=f"corr-{msg_id}",
        trace_id=f"trace-{msg_id}",
    )


def _make_domain_with_lanes(
    enabled=False, threshold=0, backfill_suffix="backfill", name="TestLanes"
):
    """Create a Domain with priority_lanes server configuration."""
    config = {
        "enable_outbox": True,
        "server": {
            "default_subscription_type": "stream",
            "priority_lanes": {
                "enabled": enabled,
                "threshold": threshold,
                "backfill_suffix": backfill_suffix,
            },
        },
    }
    domain = Domain(name=name, config=config)
    domain.register(DummyAggregate)
    domain.register(DummyEvent, part_of=DummyAggregate)
    domain.init(traverse=False)
    return domain


@pytest.fixture
def outbox_domain(test_domain):
    """`test_domain` with outbox enabled and test elements registered."""
    test_domain.config["enable_outbox"] = True
    test_domain.config["server"]["default_subscription_type"] = "stream"

    test_domain.register(DummyAggregate)
    test_domain.register(DummyEvent, part_of=DummyAggregate)
    test_domain.init(traverse=False)

    return test_domain


@pytest.mark.database
class TestPriorityLaneRouting:
    """Tests for OutboxProcessor lane routing via _publish_message()."""

    @pytest.mark.asyncio
    async def test_lanes_disabled_publishes_to_default_stream(self, outbox_domain):
        """When priority_lanes.enabled=false, all messages go to the default stream_category."""
        # Ensure lanes are disabled (the default)
        outbox_domain.config.setdefault("server", {})["priority_lanes"] = {
            "enabled": False
        }

        engine = MockEngine(outbox_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Explicitly confirm lanes are disabled
        assert processor._lanes_enabled is False

        message = _create_outbox_message("msg-low", priority=-50)

        mock_broker = Mock()
        mock_broker.publish = Mock(return_value="broker-msg-id")
        processor.broker = mock_broker

        success, error = await processor._publish_message(message)

        assert success is True
        assert error is None
        mock_broker.publish.assert_called_once()

        # Stream should be the plain stream_category, not suffixed
        call_args = mock_broker.publish.call_args
        stream_name = call_args[0][0]
        assert stream_name == "customer"
        assert "backfill" not in stream_name

    @pytest.mark.asyncio
    async def test_lanes_enabled_normal_priority_to_primary(self, outbox_domain):
        """priority=0 (at threshold) goes to the primary stream."""
        outbox_domain.config.setdefault("server", {})["priority_lanes"] = {
            "enabled": True,
            "threshold": 0,
            "backfill_suffix": "backfill",
        }

        engine = MockEngine(outbox_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        assert processor._lanes_enabled is True

        message = _create_outbox_message("msg-normal", priority=0)

        mock_broker = Mock()
        mock_broker.publish = Mock(return_value="broker-msg-id")
        processor.broker = mock_broker

        success, error = await processor._publish_message(message)

        assert success is True
        stream_name = mock_broker.publish.call_args[0][0]
        assert stream_name == "customer"

    @pytest.mark.asyncio
    async def test_lanes_enabled_high_priority_to_primary(self, outbox_domain):
        """priority=50 (above threshold) goes to the primary stream."""
        outbox_domain.config.setdefault("server", {})["priority_lanes"] = {
            "enabled": True,
            "threshold": 0,
            "backfill_suffix": "backfill",
        }

        engine = MockEngine(outbox_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        message = _create_outbox_message("msg-high", priority=50)

        mock_broker = Mock()
        mock_broker.publish = Mock(return_value="broker-msg-id")
        processor.broker = mock_broker

        success, error = await processor._publish_message(message)

        assert success is True
        stream_name = mock_broker.publish.call_args[0][0]
        assert stream_name == "customer"

    @pytest.mark.asyncio
    async def test_lanes_enabled_low_priority_to_backfill(self, outbox_domain):
        """priority=-50 (below threshold=0) goes to 'customer:backfill'."""
        outbox_domain.config.setdefault("server", {})["priority_lanes"] = {
            "enabled": True,
            "threshold": 0,
            "backfill_suffix": "backfill",
        }

        engine = MockEngine(outbox_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        message = _create_outbox_message("msg-low", priority=-50)

        mock_broker = Mock()
        mock_broker.publish = Mock(return_value="broker-msg-id")
        processor.broker = mock_broker

        success, error = await processor._publish_message(message)

        assert success is True
        stream_name = mock_broker.publish.call_args[0][0]
        assert stream_name == "customer:backfill"

    @pytest.mark.asyncio
    async def test_lanes_enabled_bulk_priority_to_backfill(self, outbox_domain):
        """priority=-100 (well below threshold) goes to 'customer:backfill'."""
        outbox_domain.config.setdefault("server", {})["priority_lanes"] = {
            "enabled": True,
            "threshold": 0,
            "backfill_suffix": "backfill",
        }

        engine = MockEngine(outbox_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        message = _create_outbox_message("msg-bulk", priority=-100)

        mock_broker = Mock()
        mock_broker.publish = Mock(return_value="broker-msg-id")
        processor.broker = mock_broker

        success, error = await processor._publish_message(message)

        assert success is True
        stream_name = mock_broker.publish.call_args[0][0]
        assert stream_name == "customer:backfill"

    @pytest.mark.asyncio
    async def test_custom_threshold(self, outbox_domain):
        """With threshold=-25, priority=-50 goes to backfill but priority=-10 stays primary."""
        outbox_domain.config.setdefault("server", {})["priority_lanes"] = {
            "enabled": True,
            "threshold": -25,
            "backfill_suffix": "backfill",
        }

        engine = MockEngine(outbox_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        assert processor._lane_threshold == -25

        mock_broker = Mock()
        mock_broker.publish = Mock(return_value="broker-msg-id")
        processor.broker = mock_broker

        # priority=-50 is below threshold=-25 --> backfill
        msg_below = _create_outbox_message("msg-below", priority=-50)
        success, _ = await processor._publish_message(msg_below)
        assert success is True
        stream_below = mock_broker.publish.call_args[0][0]
        assert stream_below == "customer:backfill"

        mock_broker.publish.reset_mock()

        # priority=-10 is above threshold=-25 --> primary
        msg_above = _create_outbox_message("msg-above", priority=-10)
        success, _ = await processor._publish_message(msg_above)
        assert success is True
        stream_above = mock_broker.publish.call_args[0][0]
        assert stream_above == "customer"

    @pytest.mark.asyncio
    async def test_custom_backfill_suffix(self, outbox_domain):
        """backfill_suffix='migration' makes the lane 'customer:migration'."""
        outbox_domain.config.setdefault("server", {})["priority_lanes"] = {
            "enabled": True,
            "threshold": 0,
            "backfill_suffix": "migration",
        }

        engine = MockEngine(outbox_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        assert processor._backfill_suffix == "migration"

        message = _create_outbox_message("msg-migrate", priority=-50)

        mock_broker = Mock()
        mock_broker.publish = Mock(return_value="broker-msg-id")
        processor.broker = mock_broker

        success, error = await processor._publish_message(message)

        assert success is True
        stream_name = mock_broker.publish.call_args[0][0]
        assert stream_name == "customer:migration"

    @pytest.mark.asyncio
    async def test_batch_mixed_priorities(self, outbox_domain):
        """A batch of messages with mixed priorities routes each correctly."""
        outbox_domain.config.setdefault("server", {})["priority_lanes"] = {
            "enabled": True,
            "threshold": 0,
            "backfill_suffix": "backfill",
        }

        engine = MockEngine(outbox_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        published_streams = []

        def capture_publish(stream_name, message_dict):
            published_streams.append(stream_name)
            return f"broker-msg-id-{len(published_streams)}"

        mock_broker = Mock()
        mock_broker.publish = Mock(side_effect=capture_publish)
        processor.broker = mock_broker

        # Create messages with varying priorities
        test_cases = [
            ("high", 50, "customer"),  # Above threshold -> primary
            ("normal", 0, "customer"),  # At threshold -> primary
            ("low", -10, "customer:backfill"),  # Below threshold -> backfill
            ("bulk", -100, "customer:backfill"),  # Well below -> backfill
            ("critical", 100, "customer"),  # Far above -> primary
        ]

        for msg_id, priority, expected_stream in test_cases:
            message = _create_outbox_message(msg_id, priority=priority)
            success, error = await processor._publish_message(message)
            assert success is True, f"Failed for message {msg_id}"

        # Verify each message was routed to the correct stream
        assert len(published_streams) == len(test_cases)
        for i, (msg_id, _, expected_stream) in enumerate(test_cases):
            assert published_streams[i] == expected_stream, (
                f"Message '{msg_id}' published to '{published_streams[i]}', "
                f"expected '{expected_stream}'"
            )

    @pytest.mark.asyncio
    async def test_lane_routing_preserves_message_content(self, outbox_domain):
        """Data and metadata are unchanged after routing, regardless of lane."""
        outbox_domain.config.setdefault("server", {})["priority_lanes"] = {
            "enabled": True,
            "threshold": 0,
            "backfill_suffix": "backfill",
        }

        engine = MockEngine(outbox_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        original_data = {"name": "Test preserved", "count": 42}
        metadata = _make_metadata("preserved-msg", stream_category="customer")

        message = Outbox.create_message(
            message_id="preserved-msg",
            stream_name="test-stream",
            message_type="DummyEvent",
            data=original_data,
            metadata=metadata,
            priority=-50,  # Will route to backfill
            correlation_id="corr-preserved",
            trace_id="trace-preserved",
        )

        captured_payloads = []

        def capture_publish(stream_name, message_dict):
            captured_payloads.append((stream_name, message_dict))
            return "broker-msg-id"

        mock_broker = Mock()
        mock_broker.publish = Mock(side_effect=capture_publish)
        processor.broker = mock_broker

        success, error = await processor._publish_message(message)

        assert success is True
        assert len(captured_payloads) == 1

        stream_name, payload = captured_payloads[0]

        # Routed to backfill lane
        assert stream_name == "customer:backfill"

        # Data preserved exactly
        assert payload["data"] == original_data

        # Metadata preserved (headers should contain the original message id)
        assert payload["metadata"]["headers"]["id"] == "preserved-msg"
        assert payload["metadata"]["headers"]["type"] == "DummyEvent"
        assert payload["metadata"]["domain"]["stream_category"] == "customer"

    def test_lanes_config_defaults(self):
        """Missing config yields enabled=false, threshold=0, suffix='backfill'."""
        # Domain with no priority_lanes configuration at all
        domain = Domain(name="TestLanesDefaults")
        domain.config["enable_outbox"] = True
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)
            processor = OutboxProcessor(engine, "default", "default")

            assert processor._lanes_enabled is False
            assert processor._lane_threshold == 0
            assert processor._backfill_suffix == "backfill"


@pytest.mark.database
class TestBoundaryPriority:
    """Tests for priority values at exact threshold boundaries."""

    @pytest.mark.asyncio
    async def test_priority_minus_one_at_threshold_zero_goes_to_backfill(
        self, outbox_domain
    ):
        """priority=-1 (immediately below threshold=0) goes to backfill."""
        outbox_domain.config.setdefault("server", {})["priority_lanes"] = {
            "enabled": True,
            "threshold": 0,
            "backfill_suffix": "backfill",
        }

        engine = MockEngine(outbox_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        message = _create_outbox_message("msg-boundary", priority=-1)

        mock_broker = Mock()
        mock_broker.publish = Mock(return_value="broker-msg-id")
        processor.broker = mock_broker

        success, error = await processor._publish_message(message)

        assert success is True
        stream_name = mock_broker.publish.call_args[0][0]
        assert stream_name == "customer:backfill"

    @pytest.mark.asyncio
    async def test_priority_at_exact_threshold_stays_primary(self, outbox_domain):
        """priority=threshold (exact match) stays on primary (not strict less-than)."""
        outbox_domain.config.setdefault("server", {})["priority_lanes"] = {
            "enabled": True,
            "threshold": -25,
            "backfill_suffix": "backfill",
        }

        engine = MockEngine(outbox_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Priority exactly equals threshold
        message = _create_outbox_message("msg-exact", priority=-25)

        mock_broker = Mock()
        mock_broker.publish = Mock(return_value="broker-msg-id")
        processor.broker = mock_broker

        success, error = await processor._publish_message(message)

        assert success is True
        stream_name = mock_broker.publish.call_args[0][0]
        assert stream_name == "customer"  # At threshold = primary

    @pytest.mark.asyncio
    async def test_priority_one_below_custom_threshold(self, outbox_domain):
        """priority=threshold-1 goes to backfill."""
        outbox_domain.config.setdefault("server", {})["priority_lanes"] = {
            "enabled": True,
            "threshold": -25,
            "backfill_suffix": "backfill",
        }

        engine = MockEngine(outbox_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        message = _create_outbox_message("msg-just-below", priority=-26)

        mock_broker = Mock()
        mock_broker.publish = Mock(return_value="broker-msg-id")
        processor.broker = mock_broker

        success, error = await processor._publish_message(message)

        assert success is True
        stream_name = mock_broker.publish.call_args[0][0]
        assert stream_name == "customer:backfill"


@pytest.mark.database
class TestEdgeCases:
    """Edge case tests for OutboxProcessor lane routing."""

    @pytest.mark.asyncio
    async def test_lanes_enabled_with_none_stream_category(self, outbox_domain):
        """When metadata has no stream_category, message is published without crash."""
        outbox_domain.config.setdefault("server", {})["priority_lanes"] = {
            "enabled": True,
            "threshold": 0,
            "backfill_suffix": "backfill",
        }

        engine = MockEngine(outbox_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Create a message with no stream_category in metadata
        headers = MessageHeaders(id="no-cat", type="DummyEvent", stream="test")
        # domain_meta with no stream_category
        domain_meta = DomainMeta()
        metadata = Metadata(headers=headers, domain=domain_meta)

        message = Outbox.create_message(
            message_id="no-cat",
            stream_name="test",
            message_type="DummyEvent",
            data={"name": "No Category"},
            metadata=metadata,
            priority=-50,
        )

        mock_broker = Mock()
        mock_broker.publish = Mock(return_value="broker-msg-id")
        processor.broker = mock_broker

        success, error = await processor._publish_message(message)

        assert success is True
        # Should publish to None/empty stream_category (no backfill suffix added)
        stream_name = mock_broker.publish.call_args[0][0]
        assert "backfill" not in (stream_name or "")

    @pytest.mark.asyncio
    async def test_lanes_enabled_with_no_domain_meta(self, outbox_domain):
        """When metadata.domain is None, message is published without crash."""
        outbox_domain.config.setdefault("server", {})["priority_lanes"] = {
            "enabled": True,
            "threshold": 0,
            "backfill_suffix": "backfill",
        }

        engine = MockEngine(outbox_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        headers = MessageHeaders(id="no-domain", type="DummyEvent", stream="test")
        metadata = Metadata(headers=headers, domain=None)

        message = Outbox.create_message(
            message_id="no-domain",
            stream_name="test",
            message_type="DummyEvent",
            data={"name": "No Domain Meta"},
            metadata=metadata,
            priority=-50,
        )

        mock_broker = Mock()
        mock_broker.publish = Mock(return_value="broker-msg-id")
        processor.broker = mock_broker

        success, error = await processor._publish_message(message)

        assert success is True
        stream_name = mock_broker.publish.call_args[0][0]
        # stream_category is None, so no backfill routing
        assert stream_name is None
