"""Tests for correlation_id and causation_id propagation in MessageTrace events.

Verifies that:
- MessageTrace dataclass includes correlation_id and causation_id fields
- TraceEmitter.emit() accepts and passes through correlation/causation IDs
- JSON serialization includes the new fields (None serializes as null)
- Engine.handle_message() propagates IDs from message metadata to trace events
"""

import json
from dataclasses import asdict

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.domain import Processing
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.tracing import TRACE_STREAM, MessageTrace, TraceEmitter
from protean.utils.eventing import (
    DomainMeta,
    Message,
    MessageHeaders,
    Metadata,
)
from protean.utils.mixins import handle


class RecordingRedis:
    """Stands in for the Redis server that TraceEmitter writes traces to."""

    def __init__(self):
        self.stream_entries = []

    def xadd(self, name, fields, **kwargs):
        self.stream_entries.append((name, fields))

    def publish(self, channel, message):
        pass

    def pubsub_numsub(self, channel):
        return []

    def traces(self):
        return [
            json.loads(fields["data"])
            for name, fields in self.stream_entries
            if name == TRACE_STREAM
        ]


def _attach_recording_redis(emitter: TraceEmitter) -> RecordingRedis:
    redis = RecordingRedis()
    emitter._redis = redis
    emitter._persist = True
    emitter._initialized = True
    return redis


# --- MessageTrace dataclass tests ---


class TestMessageTraceFields:
    """Verify the MessageTrace dataclass has correlation_id and causation_id."""

    @pytest.mark.parametrize(
        "ids, expected",
        [
            ({}, (None, None)),
            (
                {"correlation_id": "corr-abc", "causation_id": "cause-xyz"},
                ("corr-abc", "cause-xyz"),
            ),
        ],
    )
    def test_ids_on_attributes_asdict_and_json(self, ids, expected):
        trace = MessageTrace(
            event="handler.started",
            domain="test",
            stream="test::user",
            message_id="msg-1",
            message_type="UserRegistered",
            status="ok",
            **ids,
        )
        d = asdict(trace)
        data = json.loads(trace.to_json())

        assert (trace.correlation_id, trace.causation_id) == expected
        assert (d["correlation_id"], d["causation_id"]) == expected
        assert (data["correlation_id"], data["causation_id"]) == expected


# --- TraceEmitter tests ---


class TestTraceEmitterEmit:
    """Verify TraceEmitter.emit() accepts and forwards correlation/causation IDs."""

    @pytest.mark.parametrize(
        "ids, expected",
        [
            (
                {"correlation_id": "corr-123", "causation_id": "cause-456"},
                ("corr-123", "cause-456"),
            ),
            # Omitting the IDs results in None.
            ({}, (None, None)),
        ],
    )
    def test_emit_writes_ids_to_trace(self, test_domain, ids, expected):
        emitter = TraceEmitter(test_domain)
        redis = _attach_recording_redis(emitter)

        emitter.emit(
            event="handler.started",
            stream="test::user",
            message_id="msg-1",
            message_type="UserRegistered",
            **ids,
        )

        (trace,) = redis.traces()
        assert (trace["correlation_id"], trace["causation_id"]) == expected


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

        redis = _attach_recording_redis(engine.emitter)

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
        emitted = redis.traces()

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

        redis = _attach_recording_redis(engine.emitter)

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
        emitted = redis.traces()

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

        redis = _attach_recording_redis(engine.emitter)

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

        emitted = redis.traces()
        assert len(emitted) >= 2
        started = [t for t in emitted if t.get("event") == "handler.started"]
        assert len(started) == 1
        assert started[0]["correlation_id"] is None
        assert started[0]["causation_id"] is None
