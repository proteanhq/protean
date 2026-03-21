"""Tests for correlation_id and causation_id propagation in MessageTrace events.

Verifies that:
- MessageTrace dataclass includes correlation_id and causation_id fields
- TraceEmitter.emit() accepts and passes through correlation/causation IDs
- JSON serialization includes the new fields (None serializes as null)
- Engine.handle_message() propagates IDs from message metadata to trace events
"""

import json
from dataclasses import asdict
from unittest.mock import patch

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.domain import Processing
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.tracing import MessageTrace, TraceEmitter
from protean.utils.eventing import (
    DomainMeta,
    Message,
    MessageHeaders,
    Metadata,
)
from protean.utils.mixins import handle


# --- MessageTrace dataclass tests ---


class TestMessageTraceFields:
    """Verify the MessageTrace dataclass has correlation_id and causation_id."""

    def test_default_values_are_none(self):
        trace = MessageTrace(
            event="handler.started",
            domain="test",
            stream="test::user",
            message_id="msg-1",
            message_type="UserRegistered",
            status="ok",
        )
        assert trace.correlation_id is None
        assert trace.causation_id is None

    def test_explicit_values(self):
        trace = MessageTrace(
            event="handler.completed",
            domain="test",
            stream="test::user",
            message_id="msg-1",
            message_type="UserRegistered",
            status="ok",
            correlation_id="corr-abc",
            causation_id="cause-xyz",
        )
        assert trace.correlation_id == "corr-abc"
        assert trace.causation_id == "cause-xyz"

    def test_asdict_includes_fields(self):
        trace = MessageTrace(
            event="handler.started",
            domain="test",
            stream="test::user",
            message_id="msg-1",
            message_type="UserRegistered",
            status="ok",
            correlation_id="corr-abc",
            causation_id="cause-xyz",
        )
        d = asdict(trace)
        assert "correlation_id" in d
        assert "causation_id" in d
        assert d["correlation_id"] == "corr-abc"
        assert d["causation_id"] == "cause-xyz"

    def test_asdict_with_none_values(self):
        trace = MessageTrace(
            event="handler.started",
            domain="test",
            stream="test::user",
            message_id="msg-1",
            message_type="UserRegistered",
            status="ok",
        )
        d = asdict(trace)
        assert "correlation_id" in d
        assert "causation_id" in d
        assert d["correlation_id"] is None
        assert d["causation_id"] is None


class TestMessageTraceJsonSerialization:
    """Verify JSON serialization includes correlation_id and causation_id."""

    def test_json_with_ids(self):
        trace = MessageTrace(
            event="handler.completed",
            domain="test",
            stream="test::user",
            message_id="msg-1",
            message_type="UserRegistered",
            status="ok",
            correlation_id="corr-abc",
            causation_id="cause-xyz",
        )
        data = json.loads(trace.to_json())
        assert data["correlation_id"] == "corr-abc"
        assert data["causation_id"] == "cause-xyz"

    def test_json_with_none_values(self):
        trace = MessageTrace(
            event="handler.started",
            domain="test",
            stream="test::user",
            message_id="msg-1",
            message_type="UserRegistered",
            status="ok",
        )
        data = json.loads(trace.to_json())
        assert data["correlation_id"] is None
        assert data["causation_id"] is None


# --- TraceEmitter tests ---


class TestTraceEmitterEmit:
    """Verify TraceEmitter.emit() accepts and forwards correlation/causation IDs."""

    def test_emit_passes_correlation_id_to_trace(self, test_domain):
        """Verify that emit() constructs a MessageTrace with the provided IDs."""
        emitter = TraceEmitter(test_domain)

        # Force emitter to think persistence is on and Redis is available
        emitter._persist = True
        emitter._initialized = True

        traces_emitted = []

        # Patch MessageTrace construction to capture what's created
        original_init = MessageTrace.__init__

        def capturing_init(self_trace, *args, **kwargs):
            original_init(self_trace, *args, **kwargs)
            traces_emitted.append(self_trace)

        with patch.object(MessageTrace, "__init__", capturing_init):
            emitter._redis = type(
                "FakeRedis",
                (),
                {
                    "xadd": lambda *a, **kw: None,
                    "publish": lambda *a, **kw: None,
                    "pubsub_numsub": lambda *a, **kw: [],
                },
            )()

            emitter.emit(
                event="handler.started",
                stream="test::user",
                message_id="msg-1",
                message_type="UserRegistered",
                correlation_id="corr-123",
                causation_id="cause-456",
            )

        assert len(traces_emitted) > 0
        trace = traces_emitted[0]
        assert trace.correlation_id == "corr-123"
        assert trace.causation_id == "cause-456"

    def test_emit_without_ids_defaults_to_none(self, test_domain):
        """Backward compatibility: omitting IDs results in None."""
        emitter = TraceEmitter(test_domain)
        emitter._persist = True
        emitter._initialized = True

        traces_emitted = []
        original_init = MessageTrace.__init__

        def capturing_init(self_trace, *args, **kwargs):
            original_init(self_trace, *args, **kwargs)
            traces_emitted.append(self_trace)

        with patch.object(MessageTrace, "__init__", capturing_init):
            emitter._redis = type(
                "FakeRedis",
                (),
                {
                    "xadd": lambda *a, **kw: None,
                    "publish": lambda *a, **kw: None,
                    "pubsub_numsub": lambda *a, **kw: [],
                },
            )()

            emitter.emit(
                event="handler.started",
                stream="test::user",
                message_id="msg-1",
                message_type="UserRegistered",
            )

        assert len(traces_emitted) > 0
        trace = traces_emitted[0]
        assert trace.correlation_id is None
        assert trace.causation_id is None


# --- Engine.handle_message integration tests ---


class User(BaseAggregate):
    email = String()
    name = String()


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def on_registered(self, event: Registered) -> None:
        pass  # no-op handler for testing traces


class FailingEventHandler(BaseEventHandler):
    @handle(Registered)
    def on_registered(self, event: Registered) -> None:
        raise RuntimeError("boom")


@pytest.fixture(autouse=True)
def set_async_processing(test_domain):
    test_domain.config["message_processing"] = Processing.ASYNC.value


class TestEngineHandleMessageCorrelation:
    """Verify Engine.handle_message() passes correlation/causation to emitter."""

    @pytest.mark.asyncio
    async def test_handler_started_and_completed_carry_ids(self, test_domain):
        test_domain.register(User)
        test_domain.register(Registered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(domain=test_domain, test_mode=True)

        # Collect emitted traces
        emitted = []

        def capturing_emit(*args, **kwargs):
            emitted.append(kwargs)

        engine.emitter.emit = capturing_emit

        # Use the actual __type__ that the domain assigned
        event_type = Registered.__type__

        message = Message(
            data={"id": "user-1", "email": "a@b.com", "name": "Alice"},
            metadata=Metadata(
                headers=MessageHeaders(
                    id="evt-001",
                    type=event_type,
                    stream="test::user-123",
                ),
                domain=DomainMeta(
                    kind="EVENT",
                    stream_category="test::user",
                    correlation_id="corr-flow-1",
                    causation_id="cmd-parent-1",
                ),
            ),
        )

        result = await engine.handle_message(UserEventHandler, message)
        assert result is True

        # Verify we got handler.started and handler.completed
        assert len(emitted) >= 2, f"Expected at least 2 traces, got {len(emitted)}"

        started = [t for t in emitted if t.get("event") == "handler.started"]
        completed = [t for t in emitted if t.get("event") == "handler.completed"]

        assert len(started) == 1
        assert started[0]["correlation_id"] == "corr-flow-1"
        assert started[0]["causation_id"] == "cmd-parent-1"

        assert len(completed) == 1
        assert completed[0]["correlation_id"] == "corr-flow-1"
        assert completed[0]["causation_id"] == "cmd-parent-1"

    @pytest.mark.asyncio
    async def test_handler_failed_carries_ids(self, test_domain):
        test_domain.register(User)
        test_domain.register(Registered, part_of=User)
        test_domain.register(FailingEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(domain=test_domain, test_mode=True)

        emitted = []

        def capturing_emit(*args, **kwargs):
            emitted.append(kwargs)

        engine.emitter.emit = capturing_emit

        event_type = Registered.__type__

        message = Message(
            data={"id": "user-2", "email": "b@c.com", "name": "Bob"},
            metadata=Metadata(
                headers=MessageHeaders(
                    id="evt-002",
                    type=event_type,
                    stream="test::user-456",
                ),
                domain=DomainMeta(
                    kind="EVENT",
                    stream_category="test::user",
                    correlation_id="corr-fail-1",
                    causation_id="cmd-parent-2",
                ),
            ),
        )

        result = await engine.handle_message(FailingEventHandler, message)
        assert result is False  # Handler failed

        failed = [t for t in emitted if t.get("event") == "handler.failed"]
        assert len(failed) == 1
        assert failed[0]["correlation_id"] == "corr-fail-1"
        assert failed[0]["causation_id"] == "cmd-parent-2"
        assert failed[0]["status"] == "error"

    @pytest.mark.asyncio
    async def test_missing_correlation_defaults_to_none(self, test_domain):
        test_domain.register(User)
        test_domain.register(Registered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(domain=test_domain, test_mode=True)

        emitted = []

        def capturing_emit(*args, **kwargs):
            emitted.append(kwargs)

        engine.emitter.emit = capturing_emit

        event_type = Registered.__type__

        # Message with domain metadata but no correlation/causation IDs
        message = Message(
            data={"id": "user-3", "email": "c@d.com", "name": "Carol"},
            metadata=Metadata(
                headers=MessageHeaders(
                    id="evt-003",
                    type=event_type,
                    stream="test::user-789",
                ),
                domain=DomainMeta(
                    kind="EVENT",
                    stream_category="test::user",
                ),
            ),
        )

        await engine.handle_message(UserEventHandler, message)

        assert len(emitted) >= 2
        started = [t for t in emitted if t.get("event") == "handler.started"]
        assert len(started) == 1
        assert started[0]["correlation_id"] is None
        assert started[0]["causation_id"] is None
