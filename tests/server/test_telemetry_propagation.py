"""Tests for W3C TraceParent ↔ OpenTelemetry context propagation.

Verifies that:
- ``extract_context_from_traceparent()`` converts a Protean ``TraceParent``
  into an OTEL ``Context`` whose trace/span IDs match the header.
- ``inject_traceparent_from_context()`` captures the current OTEL span
  context as a ``TraceParent`` value object.
- ``Engine.handle_message()`` uses an incoming ``traceparent`` header as
  the parent of its processing span.
- ``CommandProcessor.process()`` uses an incoming ``traceparent`` header as
  the parent of its processing span.
- ``CommandProcessor.enrich()`` injects the current span context as
  ``traceparent`` into command headers.
- Events raised during handler execution carry the active span's
  ``traceparent`` forward.
- Round-trip: command with external trace → processing → events carry same
  ``trace_id`` with new ``parent_id``.
"""

from unittest.mock import Mock
from uuid import uuid4

import pytest

from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.utils.eventing import (
    Message,
    MessageHeaders,
    Metadata,
    TraceParent,
)
from protean.utils.globals import current_domain
from protean.utils.mixins import handle
from protean.utils.telemetry import (
    extract_context_from_traceparent,
    inject_traceparent_from_context,
)


# ---------------------------------------------------------------------------
# Domain elements for testing
# ---------------------------------------------------------------------------


class User(BaseAggregate):
    user_id = Identifier(identifier=True)
    name = String(required=True)
    email = String(required=True)


class RegisterUser(BaseCommand):
    user_id = Identifier(identifier=True)
    name = String(required=True)
    email = String(required=True)


class UserRegistered(BaseEvent):
    user_id = Identifier(identifier=True)
    name = String(required=True)
    email = String(required=True)


class UserCommandHandler(BaseCommandHandler):
    @handle(RegisterUser)
    def register(self, command: RegisterUser):
        user = User(
            user_id=command.user_id, name=command.name, email=command.email
        )
        user.raise_(
            UserRegistered(
                user_id=command.user_id,
                name=command.name,
                email=command.email,
            )
        )
        current_domain.repository_for(User).add(user)
        return {"registered": command.user_id}


class UserEventHandler(BaseEventHandler):
    @handle(UserRegistered)
    def on_registered(self, event: UserRegistered):
        pass  # Just consume the event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_telemetry_in_memory(domain):
    """Set up in-memory OTEL exporters on the domain for testing."""
    resource = Resource.create({"service.name": domain.normalized_name})

    span_exporter = InMemorySpanExporter()
    tracer_provider = SDKTracerProvider(resource=resource)
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

    metric_reader = InMemoryMetricReader()
    meter_provider = SDKMeterProvider(
        resource=resource, metric_readers=[metric_reader]
    )

    domain._otel_tracer_provider = tracer_provider
    domain._otel_meter_provider = meter_provider
    domain._otel_init_attempted = True

    return span_exporter


# A known W3C traceparent header for testing
EXTERNAL_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
EXTERNAL_SPAN_ID = "00f067aa0ba902b7"
EXTERNAL_TRACEPARENT = f"00-{EXTERNAL_TRACE_ID}-{EXTERNAL_SPAN_ID}-01"


class _FakeEngine:
    """Minimal Engine stand-in for tests that call handle_message() directly."""

    def __init__(self, domain):
        self.domain = domain
        self.loop = None
        self.emitter = Mock()
        self.shutting_down = False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(RegisterUser, part_of=User)
    test_domain.register(UserCommandHandler, part_of=User)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.init(traverse=False)


@pytest.fixture()
def span_exporter(test_domain):
    """Enable in-memory OTEL and return the span exporter."""
    return _init_telemetry_in_memory(test_domain)


# ---------------------------------------------------------------------------
# Tests: Helper functions
# ---------------------------------------------------------------------------


class TestExtractContextFromTraceparent:
    """extract_context_from_traceparent() converts TraceParent → OTEL Context."""

    def test_returns_none_when_traceparent_is_none(self):
        assert extract_context_from_traceparent(None) is None

    def test_extracts_trace_id_and_span_id(self):
        tp = TraceParent.build(EXTERNAL_TRACEPARENT)
        ctx = extract_context_from_traceparent(tp)
        assert ctx is not None

        from opentelemetry import trace

        span = trace.get_current_span(ctx)
        sc = span.get_span_context()
        assert f"{sc.trace_id:032x}" == EXTERNAL_TRACE_ID
        assert f"{sc.span_id:016x}" == EXTERNAL_SPAN_ID

    def test_preserves_sampled_flag(self):
        tp = TraceParent.build(EXTERNAL_TRACEPARENT)
        ctx = extract_context_from_traceparent(tp)

        from opentelemetry import trace
        from opentelemetry.trace import TraceFlags

        sc = trace.get_current_span(ctx).get_span_context()
        assert sc.trace_flags & TraceFlags.SAMPLED

    def test_unsampled_flag(self):
        tp = TraceParent.build(f"00-{EXTERNAL_TRACE_ID}-{EXTERNAL_SPAN_ID}-00")
        ctx = extract_context_from_traceparent(tp)

        from opentelemetry import trace
        from opentelemetry.trace import TraceFlags

        sc = trace.get_current_span(ctx).get_span_context()
        assert not (sc.trace_flags & TraceFlags.SAMPLED)


class TestInjectTraceparentFromContext:
    """inject_traceparent_from_context() captures current span as TraceParent."""

    def test_returns_none_without_active_span(self):
        # When no SDK tracer provider is set up, there's no active span
        # so inject should return None
        result = inject_traceparent_from_context()
        assert result is None

    def test_captures_active_span_context(self):
        provider = SDKTracerProvider()
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("test-span") as span:
            tp = inject_traceparent_from_context()

        assert tp is not None
        sc = span.get_span_context()
        assert tp.trace_id == f"{sc.trace_id:032x}"
        assert tp.parent_id == f"{sc.span_id:016x}"
        assert tp.sampled is True


# ---------------------------------------------------------------------------
# Tests: CommandProcessor.process() context extraction
# ---------------------------------------------------------------------------


class TestCommandProcessContextExtraction:
    """CommandProcessor.process() uses incoming traceparent as parent context."""

    def test_process_span_is_child_of_incoming_traceparent(
        self, test_domain, span_exporter
    ):
        tp = TraceParent.build(EXTERNAL_TRACEPARENT)
        command = RegisterUser(
            user_id=str(uuid4()),
            name="Alice",
            email="alice@example.com",
            _metadata=Metadata(headers=MessageHeaders(traceparent=tp)),
        )

        test_domain.process(command, asynchronous=False)

        spans = span_exporter.get_finished_spans()
        process_span = next(
            s for s in spans if s.name == "protean.command.process"
        )

        # The process span must share the external trace_id
        assert (
            f"{process_span.context.trace_id:032x}" == EXTERNAL_TRACE_ID
        )
        # Its parent must be the external span_id
        assert process_span.parent is not None
        assert (
            f"{process_span.parent.span_id:016x}" == EXTERNAL_SPAN_ID
        )

    def test_process_span_without_traceparent_is_root(
        self, test_domain, span_exporter
    ):
        command = RegisterUser(
            user_id=str(uuid4()),
            name="Bob",
            email="bob@example.com",
        )

        test_domain.process(command, asynchronous=False)

        spans = span_exporter.get_finished_spans()
        process_span = next(
            s for s in spans if s.name == "protean.command.process"
        )

        # Without an incoming traceparent, the process span is a root span
        assert process_span.parent is None


# ---------------------------------------------------------------------------
# Tests: CommandProcessor.enrich() context injection
# ---------------------------------------------------------------------------


class TestCommandEnrichContextInjection:
    """CommandProcessor.enrich() injects current span as traceparent."""

    def test_enriched_command_carries_traceparent(
        self, test_domain, span_exporter
    ):
        uid = str(uuid4())
        command = RegisterUser(
            user_id=uid,
            name="Carol",
            email="carol@example.com",
        )

        enriched = test_domain._enrich_command(command, asynchronous=False)

        # The enriched command must have a traceparent injected from the
        # active enrich span.
        tp = enriched._metadata.headers.traceparent
        assert tp is not None
        assert tp.trace_id is not None
        assert tp.parent_id is not None

    def test_enriched_command_traceparent_matches_enrich_span(
        self, test_domain, span_exporter
    ):
        uid = str(uuid4())
        command = RegisterUser(
            user_id=uid,
            name="Dave",
            email="dave@example.com",
        )

        enriched = test_domain._enrich_command(command, asynchronous=False)

        tp = enriched._metadata.headers.traceparent
        assert tp is not None

        # The traceparent's trace_id and parent_id should match the enrich
        # span that was active when the headers were created.
        spans = span_exporter.get_finished_spans()
        enrich_span = next(
            s for s in spans if s.name == "protean.command.enrich"
        )
        assert tp.trace_id == f"{enrich_span.context.trace_id:032x}"
        assert tp.parent_id == f"{enrich_span.context.span_id:016x}"
        assert tp.sampled is True


# ---------------------------------------------------------------------------
# Tests: Event traceparent injection
# ---------------------------------------------------------------------------


class TestEventTraceparentInjection:
    """Events raised during handler execution carry active span's traceparent."""

    def test_event_carries_traceparent_from_processing_span(
        self, test_domain, span_exporter
    ):
        uid = str(uuid4())
        command = RegisterUser(
            user_id=uid,
            name="Eve",
            email="eve@example.com",
        )

        test_domain.process(command, asynchronous=False)

        # Read the event from the event store
        stream = f"{User.meta_.stream_category}-{uid}"
        events = test_domain.event_store.store.read(stream)

        # Find the UserRegistered event
        user_registered = [
            e for e in events if e.metadata.headers.type == UserRegistered.__type__
        ]
        assert len(user_registered) == 1

        event_msg = user_registered[0]
        assert event_msg.metadata.headers.traceparent is not None
        tp = event_msg.metadata.headers.traceparent
        assert tp.trace_id is not None
        assert tp.parent_id is not None


# ---------------------------------------------------------------------------
# Tests: Round-trip trace propagation
# ---------------------------------------------------------------------------


class TestRoundTripTracePropagation:
    """Command with external trace → processing → events carry same trace_id."""

    def test_events_share_trace_id_with_incoming_command(
        self, test_domain, span_exporter
    ):
        tp = TraceParent.build(EXTERNAL_TRACEPARENT)
        uid = str(uuid4())
        command = RegisterUser(
            user_id=uid,
            name="Frank",
            email="frank@example.com",
            _metadata=Metadata(headers=MessageHeaders(traceparent=tp)),
        )

        test_domain.process(command, asynchronous=False)

        # Read event from event store
        stream = f"{User.meta_.stream_category}-{uid}"
        events = test_domain.event_store.store.read(stream)

        user_registered = [
            e for e in events if e.metadata.headers.type == UserRegistered.__type__
        ]
        assert len(user_registered) == 1

        event_tp = user_registered[0].metadata.headers.traceparent
        assert event_tp is not None
        # The event must carry the same trace_id as the incoming command
        assert event_tp.trace_id == EXTERNAL_TRACE_ID

    def test_events_have_different_parent_id_than_incoming(
        self, test_domain, span_exporter
    ):
        tp = TraceParent.build(EXTERNAL_TRACEPARENT)
        uid = str(uuid4())
        command = RegisterUser(
            user_id=uid,
            name="Grace",
            email="grace@example.com",
            _metadata=Metadata(headers=MessageHeaders(traceparent=tp)),
        )

        test_domain.process(command, asynchronous=False)

        stream = f"{User.meta_.stream_category}-{uid}"
        events = test_domain.event_store.store.read(stream)

        user_registered = [
            e for e in events if e.metadata.headers.type == UserRegistered.__type__
        ]
        assert len(user_registered) == 1
        event_tp = user_registered[0].metadata.headers.traceparent
        assert event_tp is not None
        # The event's parent_id should be a child span, not the original external span
        assert event_tp.parent_id != EXTERNAL_SPAN_ID

    def test_full_span_tree_connectivity(self, test_domain, span_exporter):
        """Verify the span tree: external → process → enrich + handler."""
        tp = TraceParent.build(EXTERNAL_TRACEPARENT)
        uid = str(uuid4())
        command = RegisterUser(
            user_id=uid,
            name="Hank",
            email="hank@example.com",
            _metadata=Metadata(headers=MessageHeaders(traceparent=tp)),
        )

        test_domain.process(command, asynchronous=False)

        spans = span_exporter.get_finished_spans()
        span_map = {s.name: s for s in spans}

        # All spans must share the same trace_id (the external one)
        for s in spans:
            assert (
                f"{s.context.trace_id:032x}" == EXTERNAL_TRACE_ID
            ), f"Span '{s.name}' has wrong trace_id"

        # process is child of external
        process_span = span_map["protean.command.process"]
        assert f"{process_span.parent.span_id:016x}" == EXTERNAL_SPAN_ID

        # enrich is child of process
        enrich_span = span_map["protean.command.enrich"]
        assert (
            enrich_span.parent.span_id == process_span.context.span_id
        )


# ---------------------------------------------------------------------------
# Tests: Engine.handle_message() context extraction
# ---------------------------------------------------------------------------


class TestEngineHandleMessageContextExtraction:
    """Engine.handle_message() uses incoming traceparent as parent context."""

    @pytest.fixture()
    def engine(self, test_domain, span_exporter):
        from protean.server.engine import Engine

        engine = _FakeEngine(test_domain)
        engine.__class__ = type(
            "TestEngine", (Engine,), {"__init__": lambda self: None}
        )
        engine.domain = test_domain
        engine.emitter = Mock()
        engine.shutting_down = False
        return engine

    def _make_event_message_with_traceparent(self, test_domain):
        """Create an event Message with an external traceparent."""
        uid = str(uuid4())
        tp = TraceParent.build(EXTERNAL_TRACEPARENT)
        user = User(user_id=uid, name="Test", email="test@example.com")
        user.raise_(
            UserRegistered(
                user_id=uid,
                name="Test",
                email="test@example.com",
                _metadata=Metadata(
                    headers=MessageHeaders(traceparent=tp),
                ),
            )
        )
        msg = Message.from_domain_object(user._events[-1])
        return msg

    @pytest.mark.asyncio
    async def test_handle_message_span_is_child_of_incoming_traceparent(
        self, engine, test_domain, span_exporter
    ):
        msg = self._make_event_message_with_traceparent(test_domain)

        await engine.handle_message(UserEventHandler, msg)

        spans = span_exporter.get_finished_spans()
        handle_span = next(
            s for s in spans if s.name == "protean.engine.handle_message"
        )

        # The handle_message span must be a child of the external trace
        assert f"{handle_span.context.trace_id:032x}" == EXTERNAL_TRACE_ID
        assert handle_span.parent is not None
        assert f"{handle_span.parent.span_id:016x}" == EXTERNAL_SPAN_ID

    @pytest.mark.asyncio
    async def test_handle_message_without_traceparent_is_root(
        self, engine, test_domain, span_exporter
    ):
        uid = str(uuid4())
        user = User(user_id=uid, name="Test", email="test@example.com")
        user.raise_(
            UserRegistered(
                user_id=uid, name="Test", email="test@example.com"
            )
        )
        msg = Message.from_domain_object(user._events[-1])

        await engine.handle_message(UserEventHandler, msg)

        spans = span_exporter.get_finished_spans()
        handle_span = next(
            s for s in spans if s.name == "protean.engine.handle_message"
        )

        # Without traceparent, the span is a root span
        assert handle_span.parent is None


# ---------------------------------------------------------------------------
# Tests: No-op behavior when OTEL is disabled
# ---------------------------------------------------------------------------


class TestNoOpBehavior:
    """Propagation helpers degrade gracefully when OTEL is not available."""

    def test_extract_without_otel_returns_none(self, monkeypatch):
        import protean.utils.telemetry as tel_mod

        monkeypatch.setattr(tel_mod, "_OTEL_AVAILABLE", False)
        tp = TraceParent(
            trace_id=EXTERNAL_TRACE_ID, parent_id=EXTERNAL_SPAN_ID, sampled=True
        )
        assert extract_context_from_traceparent(tp) is None

    def test_inject_without_otel_returns_none(self, monkeypatch):
        import protean.utils.telemetry as tel_mod

        monkeypatch.setattr(tel_mod, "_OTEL_AVAILABLE", False)
        assert inject_traceparent_from_context() is None

    def test_process_works_without_telemetry(self, test_domain):
        """Command processing works correctly without telemetry enabled."""
        uid = str(uuid4())
        result = test_domain.process(
            RegisterUser(
                user_id=uid,
                name="NoTelemetry",
                email="notel@example.com",
            ),
            asynchronous=False,
        )
        assert result == {"registered": uid}
