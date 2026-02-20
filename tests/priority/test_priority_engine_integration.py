"""Higher-level tests for Engine pipeline integration with priority lanes.

These tests verify that priority lanes configuration correctly flows from the
domain config into OutboxProcessor and StreamSubscription instances created
by the Engine. They use mocking rather than real infrastructure (no Redis or
PostgreSQL required).

Tested behaviors:
1. Backward compatibility: no priority_lanes config -> lanes disabled.
2. Config propagation to OutboxProcessor (_lanes_enabled, _lane_threshold, _backfill_suffix).
3. Config propagation to StreamSubscription (_lanes_enabled, backfill_stream).
4. Config validation for invalid priority_lanes values.
5. Engine.handle_message restores priority from message metadata.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server.outbox_processor import OutboxProcessor
from protean.server.subscription.stream_subscription import StreamSubscription
from protean.utils.mixins import handle


# ---------------------------------------------------------------------------
# Test domain elements (minimal set required for Engine initialization)
# ---------------------------------------------------------------------------


class Account(BaseAggregate):
    email: String()
    name: String()


class AccountRegistered(BaseEvent):
    id: Identifier()
    email: String()


class RegisterAccount(BaseCommand):
    email: String()
    name: String()


def _noop(*args, **kwargs):
    pass


class AccountEventHandler(BaseEventHandler):
    @handle(AccountRegistered)
    def handle_account_registered(self, event: AccountRegistered) -> None:
        _noop(event)


class AccountCommandHandler(BaseCommandHandler):
    @handle(RegisterAccount)
    def handle_register_account(self, command: RegisterAccount) -> None:
        _noop(command)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine_mock(domain_config):
    """Build a mock engine with controllable domain config.

    This avoids standing up a real Engine (which requires event store,
    database providers, etc.) while still providing the interface that
    OutboxProcessor and StreamSubscription expect.
    """
    engine = MagicMock()
    engine.domain.config = domain_config
    engine.domain.brokers = {"default": MagicMock()}
    engine.shutting_down = False
    engine.emitter = MagicMock()
    engine.loop = asyncio.new_event_loop()
    return engine


# ---------------------------------------------------------------------------
# Test: backward compatibility -- no priority_lanes config
# ---------------------------------------------------------------------------


class TestBackwardCompatibilityNoConfig:
    """When the domain has no priority_lanes config, everything defaults to disabled."""

    def test_stream_subscription_lanes_disabled_by_default(self):
        """No priority_lanes config -> StreamSubscription._lanes_enabled is False."""

        class _FakeHandler:
            __name__ = "FakeHandler"
            __module__ = "tests.priority"
            __qualname__ = "FakeHandler"

        engine = _make_engine_mock({"server": {}})
        sub = StreamSubscription(
            engine=engine,
            stream_category="orders",
            handler=_FakeHandler,
        )

        assert sub._lanes_enabled is False
        # Backfill stream is still computed but lanes won't be used
        assert sub.backfill_stream == "orders:backfill"

    def test_outbox_processor_lanes_disabled_by_default(self):
        """No priority_lanes config -> OutboxProcessor._lanes_enabled is False."""
        engine = _make_engine_mock({"server": {}})
        processor = OutboxProcessor(engine, "default", "default")

        assert processor._lanes_enabled is False
        assert processor._lane_threshold == 0
        assert processor._backfill_suffix == "backfill"


# ---------------------------------------------------------------------------
# Test: lanes config flows to OutboxProcessor
# ---------------------------------------------------------------------------


class TestLanesConfigFlowsToOutboxProcessor:
    """Verify OutboxProcessor reads priority_lanes config from the domain."""

    def test_enabled_flag_propagates(self):
        """priority_lanes.enabled=True is reflected on OutboxProcessor._lanes_enabled."""
        engine = _make_engine_mock(
            {
                "server": {
                    "priority_lanes": {
                        "enabled": True,
                        "threshold": 0,
                        "backfill_suffix": "backfill",
                    },
                },
            }
        )
        processor = OutboxProcessor(engine, "default", "default")

        assert processor._lanes_enabled is True

    def test_threshold_propagates(self):
        """priority_lanes.threshold=-25 is reflected on OutboxProcessor._lane_threshold."""
        engine = _make_engine_mock(
            {
                "server": {
                    "priority_lanes": {
                        "enabled": True,
                        "threshold": -25,
                        "backfill_suffix": "backfill",
                    },
                },
            }
        )
        processor = OutboxProcessor(engine, "default", "default")

        assert processor._lane_threshold == -25

    def test_backfill_suffix_propagates(self):
        """priority_lanes.backfill_suffix='migration' is reflected on OutboxProcessor."""
        engine = _make_engine_mock(
            {
                "server": {
                    "priority_lanes": {
                        "enabled": True,
                        "threshold": 0,
                        "backfill_suffix": "migration",
                    },
                },
            }
        )
        processor = OutboxProcessor(engine, "default", "default")

        assert processor._backfill_suffix == "migration"

    def test_all_config_values_together(self):
        """All three config values are propagated correctly in a single processor."""
        engine = _make_engine_mock(
            {
                "server": {
                    "priority_lanes": {
                        "enabled": True,
                        "threshold": 10,
                        "backfill_suffix": "low-prio",
                    },
                },
            }
        )
        processor = OutboxProcessor(engine, "default", "default")

        assert processor._lanes_enabled is True
        assert processor._lane_threshold == 10
        assert processor._backfill_suffix == "low-prio"


# ---------------------------------------------------------------------------
# Test: lanes config flows to StreamSubscription
# ---------------------------------------------------------------------------


class TestLanesConfigFlowsToStreamSubscription:
    """Verify StreamSubscription reads priority_lanes config from the domain."""

    class _FakeHandler:
        __name__ = "FakeHandler"
        __module__ = "tests.priority"
        __qualname__ = "FakeHandler"

    def test_enabled_flag_propagates(self):
        """priority_lanes.enabled=True is reflected on StreamSubscription._lanes_enabled."""
        engine = _make_engine_mock(
            {
                "server": {
                    "priority_lanes": {
                        "enabled": True,
                        "backfill_suffix": "backfill",
                    },
                },
            }
        )
        sub = StreamSubscription(
            engine=engine,
            stream_category="customer",
            handler=self._FakeHandler,
        )

        assert sub._lanes_enabled is True

    def test_backfill_stream_name_default_suffix(self):
        """Default backfill_suffix='backfill' produces 'customer:backfill'."""
        engine = _make_engine_mock(
            {
                "server": {
                    "priority_lanes": {
                        "enabled": True,
                        "backfill_suffix": "backfill",
                    },
                },
            }
        )
        sub = StreamSubscription(
            engine=engine,
            stream_category="customer",
            handler=self._FakeHandler,
        )

        assert sub.backfill_stream == "customer:backfill"

    def test_backfill_stream_name_custom_suffix(self):
        """Custom backfill_suffix='migration' produces 'customer:migration'."""
        engine = _make_engine_mock(
            {
                "server": {
                    "priority_lanes": {
                        "enabled": True,
                        "backfill_suffix": "migration",
                    },
                },
            }
        )
        sub = StreamSubscription(
            engine=engine,
            stream_category="customer",
            handler=self._FakeHandler,
        )

        assert sub._backfill_suffix == "migration"
        assert sub.backfill_stream == "customer:migration"

    def test_all_config_values_together(self):
        """All config values are propagated correctly in a single subscription."""
        engine = _make_engine_mock(
            {
                "server": {
                    "priority_lanes": {
                        "enabled": True,
                        "backfill_suffix": "slow-lane",
                    },
                },
            }
        )
        sub = StreamSubscription(
            engine=engine,
            stream_category="orders",
            handler=self._FakeHandler,
        )

        assert sub._lanes_enabled is True
        assert sub._backfill_suffix == "slow-lane"
        assert sub.backfill_stream == "orders:slow-lane"
        # DLQ streams should also reflect the suffix
        assert sub.backfill_dlq_stream == "orders:slow-lane:dlq"

    def test_disabled_lanes_still_computes_backfill_stream(self):
        """Even when lanes are disabled, backfill_stream is computed (but unused)."""
        engine = _make_engine_mock(
            {
                "server": {
                    "priority_lanes": {
                        "enabled": False,
                        "backfill_suffix": "backfill",
                    },
                },
            }
        )
        sub = StreamSubscription(
            engine=engine,
            stream_category="orders",
            handler=self._FakeHandler,
        )

        assert sub._lanes_enabled is False
        # Still computed, just not used in the poll() loop
        assert sub.backfill_stream == "orders:backfill"


# ---------------------------------------------------------------------------
# Test: Engine.handle_message restores priority from message metadata
# ---------------------------------------------------------------------------


class TestEnginePriorityRestoration:
    """Verify Engine.handle_message wraps handler in processing_priority()
    using the priority stored in the message's DomainMeta."""

    @pytest.mark.asyncio
    async def test_handle_message_sets_priority_context(self):
        """Engine.handle_message wraps handler in processing_priority(metadata.priority)."""
        from protean.utils.processing import current_priority
        from protean.utils.eventing import (
            Message,
            Metadata,
            MessageHeaders,
            DomainMeta,
        )
        from protean.server.engine import Engine

        captured_priority = []

        class _PriorityCapturingHandler:
            __name__ = "PriorityCapturingHandler"
            __module__ = "tests.priority"
            __qualname__ = "PriorityCapturingHandler"
            element_type = None

            @classmethod
            def _handle(cls, message):
                captured_priority.append(current_priority())

            @classmethod
            def handle_error(cls, exc, message):
                pass

        # Build a message with priority=-50 in DomainMeta
        headers = MessageHeaders(id="test-1", type="TestEvent", stream="test")
        domain_meta = DomainMeta(
            kind="COMMAND",
            stream_category="test",
            priority=-50,
        )
        metadata = Metadata(headers=headers, domain=domain_meta)
        message = Message(data={"test": True}, metadata=metadata)

        # Build a minimal engine mock
        engine = MagicMock()
        engine.shutting_down = False
        engine.emitter = MagicMock()

        # We need a real domain context, so create a minimal domain
        from protean.domain import Domain

        domain = Domain(name="TestPriorityEngine")
        engine.domain = domain

        with domain.domain_context():
            result = await Engine.handle_message(
                engine, _PriorityCapturingHandler, message
            )

        assert result is True
        assert len(captured_priority) == 1
        assert captured_priority[0] == -50

    @pytest.mark.asyncio
    async def test_handle_message_default_priority_when_no_domain_meta(self):
        """When message has no DomainMeta, priority defaults to 0."""
        from protean.utils.processing import current_priority
        from protean.utils.eventing import (
            Message,
            Metadata,
            MessageHeaders,
        )
        from protean.server.engine import Engine

        captured_priority = []

        class _PriorityCapturingHandler:
            __name__ = "DefaultPriorityHandler"
            __module__ = "tests.priority"
            __qualname__ = "DefaultPriorityHandler"
            element_type = None

            @classmethod
            def _handle(cls, message):
                captured_priority.append(current_priority())

            @classmethod
            def handle_error(cls, exc, message):
                pass

        headers = MessageHeaders(id="test-2", type="TestEvent", stream="test")
        metadata = Metadata(headers=headers, domain=None)
        message = Message(data={"test": True}, metadata=metadata)

        engine = MagicMock()
        engine.shutting_down = False
        engine.emitter = MagicMock()

        from protean.domain import Domain

        domain = Domain(name="TestPriorityEngineDefault")
        engine.domain = domain

        with domain.domain_context():
            result = await Engine.handle_message(
                engine, _PriorityCapturingHandler, message
            )

        assert result is True
        assert len(captured_priority) == 1
        assert captured_priority[0] == 0


# ---------------------------------------------------------------------------
# Test: Config validation for priority_lanes
# ---------------------------------------------------------------------------


class TestPriorityLanesConfigValidation:
    """Verify that invalid priority_lanes config values raise ConfigurationError."""

    def test_invalid_enabled_type_raises(self):
        """enabled='yes' (string instead of bool) raises ConfigurationError."""
        from protean.domain import Domain
        from protean.exceptions import ConfigurationError

        domain = Domain(
            name="TestBadEnabled",
            config={
                "server": {
                    "priority_lanes": {
                        "enabled": "yes",  # Should be bool
                    },
                },
            },
        )

        with pytest.raises(ConfigurationError, match="must be a bool"):
            domain.init(traverse=False)

    def test_invalid_threshold_type_raises(self):
        """threshold='abc' (string instead of int) raises ConfigurationError."""
        from protean.domain import Domain
        from protean.exceptions import ConfigurationError

        domain = Domain(
            name="TestBadThreshold",
            config={
                "server": {
                    "priority_lanes": {
                        "enabled": True,
                        "threshold": "abc",  # Should be int
                    },
                },
            },
        )

        with pytest.raises(ConfigurationError, match="must be an integer"):
            domain.init(traverse=False)

    def test_bool_threshold_raises(self):
        """threshold=True (bool instead of int) raises ConfigurationError."""
        from protean.domain import Domain
        from protean.exceptions import ConfigurationError

        domain = Domain(
            name="TestBoolThreshold",
            config={
                "server": {
                    "priority_lanes": {
                        "enabled": True,
                        "threshold": True,  # bool is technically int subclass, should be rejected
                    },
                },
            },
        )

        with pytest.raises(ConfigurationError, match="must be an integer"):
            domain.init(traverse=False)

    def test_empty_backfill_suffix_raises(self):
        """backfill_suffix='' (empty string) raises ConfigurationError."""
        from protean.domain import Domain
        from protean.exceptions import ConfigurationError

        domain = Domain(
            name="TestEmptySuffix",
            config={
                "server": {
                    "priority_lanes": {
                        "enabled": True,
                        "backfill_suffix": "",  # Should be non-empty
                    },
                },
            },
        )

        with pytest.raises(ConfigurationError, match="non-empty string"):
            domain.init(traverse=False)

    def test_whitespace_only_backfill_suffix_raises(self):
        """backfill_suffix='   ' (whitespace only) raises ConfigurationError."""
        from protean.domain import Domain
        from protean.exceptions import ConfigurationError

        domain = Domain(
            name="TestWhitespaceSuffix",
            config={
                "server": {
                    "priority_lanes": {
                        "enabled": True,
                        "backfill_suffix": "   ",
                    },
                },
            },
        )

        with pytest.raises(ConfigurationError, match="non-empty string"):
            domain.init(traverse=False)

    def test_valid_config_does_not_raise(self):
        """Well-formed config passes validation without error."""
        from protean.domain import Domain

        domain = Domain(
            name="TestValidConfig",
            config={
                "server": {
                    "priority_lanes": {
                        "enabled": True,
                        "threshold": -25,
                        "backfill_suffix": "migration",
                    },
                },
            },
        )

        # Should not raise
        domain.init(traverse=False)
