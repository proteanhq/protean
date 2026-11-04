"""Tests for Engine observability instrumentation.

Verifies that handle_message emits the correct trace events
(handler.started, handler.completed, handler.failed) via the emitter.
The emitter is the real TraceEmitter; only its Redis client is a stand-in
that records what the emitter publishes.
"""

import json
from uuid import uuid4

import pytest

from protean import apply
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.process_manager import BaseProcessManager
from protean.fields import Float, Identifier, String
from protean.server import Engine
from protean.server.engine import CommandDispatcher
from protean.server.tracing import TRACE_CHANNEL, TRACE_STREAM, TraceEmitter
from protean.utils.eventing import Message
from protean.utils.globals import g
from protean.utils.mixins import handle


# Domain elements for testing
class Registered(BaseEvent):
    id: Identifier()
    email: String()


class Register(BaseCommand):
    user_id: Identifier()
    email: String()


class User(BaseAggregate):
    id: Identifier(identifier=True)
    email: String()
    name: String()

    @apply
    def on_registered(self, event: Registered) -> None:
        self.email = event.email


handler_calls = []


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def on_registered(self, event: Registered) -> None:
        handler_calls.append(event)


class UserCommandHandler(BaseCommandHandler):
    @handle(Register)
    def register(self, command: Register) -> None:
        handler_calls.append(command)


class FailingEventHandler(BaseEventHandler):
    @handle(Registered)
    def on_registered(self, event: Registered) -> None:
        raise RuntimeError("Handler exploded")


@pytest.fixture(autouse=True)
def reset_calls():
    handler_calls.clear()
    yield


class RecordingRedis:
    """Redis stand-in that keeps every trace the emitter writes, decoded
    from JSON. With ``listeners=0`` nobody is subscribed to the trace channel,
    so the emitter only writes to the trace stream."""

    def __init__(self, listeners):
        self.listeners = listeners
        self.traces = []

    def pubsub_numsub(self, channel):
        return [(channel, self.listeners)]

    def publish(self, channel, payload):
        assert channel == TRACE_CHANNEL
        self.traces.append(json.loads(payload))

    def xadd(self, stream, fields, minid, approximate):
        assert stream == TRACE_STREAM
        self.traces.append(json.loads(fields["data"]))


def _record_traces(engine, persist=False):
    """Give the engine a real TraceEmitter that writes to a recording Redis
    client, and return the list of traces it writes.

    By default the emitter only publishes to a live listener. With
    ``persist=True`` it only writes to the trace stream, with no listener.
    """
    emitter = TraceEmitter(engine.domain, trace_retention_days=7 if persist else 0)
    redis = RecordingRedis(listeners=0 if persist else 1)
    emitter._initialized = True
    emitter._redis = redis
    engine.emitter = emitter
    return redis.traces


def _traces(traces, event):
    return [t for t in traces if t["event"] == event]


def _message_context_is_clean(test_domain):
    with test_domain.domain_context():
        return not hasattr(g, "message_in_context") or g.message_in_context is None


def _make_event_message(test_domain):
    """Helper to create a valid event Message."""
    identifier = str(uuid4())
    user = User(id=identifier, email="test@example.com", name="Test")
    user.raise_(Registered(id=identifier, email="test@example.com"))
    return Message.from_domain_object(user._events[-1])


def _make_command_message(test_domain):
    """Helper to create a valid command Message."""
    identifier = str(uuid4())
    command = Register(user_id=identifier, email="test@example.com")
    enriched = test_domain._enrich_command(command, True)
    return Message.from_domain_object(enriched)


class TestHandlerTraces:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User, event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.register(FailingEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.mark.asyncio
    async def test_handler_started_and_completed_emitted_on_success(self, test_domain):
        """handle_message emits handler.started before processing and
        handler.completed with a duration on success, then clears
        g.message_in_context."""
        engine = Engine(domain=test_domain, test_mode=True)
        traces = _record_traces(engine)

        message = _make_event_message(test_domain)
        result = await engine.handle_message(UserEventHandler, message)

        assert result is True

        started = _traces(traces, "handler.started")
        assert len(started) == 1
        assert started[0]["handler"] == "UserEventHandler"
        assert started[0]["message_type"] != "unknown"
        assert started[0]["stream"] != "unknown"

        completed = _traces(traces, "handler.completed")
        assert len(completed) == 1
        assert completed[0]["handler"] == "UserEventHandler"
        assert completed[0]["duration_ms"] is not None
        assert completed[0]["duration_ms"] >= 0

        assert _message_context_is_clean(test_domain)

    @pytest.mark.asyncio
    async def test_handler_failed_emitted_on_exception(self, test_domain):
        """handle_message emits handler.failed with the error on exception,
        then clears g.message_in_context."""
        engine = Engine(domain=test_domain, test_mode=True)
        traces = _record_traces(engine)

        message = _make_event_message(test_domain)
        result = await engine.handle_message(FailingEventHandler, message)

        assert result is False

        failed = _traces(traces, "handler.failed")
        assert len(failed) == 1
        assert failed[0]["status"] == "error"
        assert failed[0]["handler"] == "FailingEventHandler"
        assert "Handler exploded" in failed[0]["error"]
        assert failed[0]["duration_ms"] is not None

        assert _message_context_is_clean(test_domain)


class TestCommandDispatcherHandlerName:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User, event_sourced=True)
        test_domain.register(Register, part_of=User)
        test_domain.register(UserCommandHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.mark.asyncio
    async def test_resolved_handler_name_for_dispatcher(self, test_domain):
        """For CommandDispatcher, emitter receives resolved handler name, not dispatcher name."""
        engine = Engine(domain=test_domain, test_mode=True)
        traces = _record_traces(engine)

        # Get the dispatcher from the subscription
        subscription_key = "commands:test::user:command"
        dispatcher = engine._subscriptions[subscription_key].handler
        assert isinstance(dispatcher, CommandDispatcher)

        message = _make_command_message(test_domain)
        await engine.handle_message(dispatcher, message)

        started = _traces(traces, "handler.started")
        assert len(started) == 1
        # Should be the specific handler name, not "Commands:test::user:command"
        assert started[0]["handler"] == "UserCommandHandler"


# --- Process Manager elements ---


class Order(BaseAggregate):
    customer_id: Identifier()
    total: Float()
    status: String(default="new")


class OrderPlaced(BaseEvent):
    order_id: Identifier()
    customer_id: Identifier()
    total: Float()


class Payment(BaseAggregate):
    order_id: Identifier()
    amount: Float()


class PaymentConfirmed(BaseEvent):
    payment_id: Identifier()
    order_id: Identifier()
    amount: Float()


class OrderFulfillmentPM(BaseProcessManager):
    order_id: Identifier()
    status: String(default="new")

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event: OrderPlaced) -> None:
        self.order_id = event.order_id
        self.status = "awaiting_payment"

    @handle(PaymentConfirmed, correlate="order_id")
    def on_payment_confirmed(self, event: PaymentConfirmed) -> None:
        self.status = "paid"


class TestPMTransitionTrace:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(Payment)
        test_domain.register(PaymentConfirmed, part_of=Payment)
        test_domain.register(
            OrderFulfillmentPM,
            stream_categories=["test::order", "test::payment"],
        )
        test_domain.init(traverse=False)

    def _make_order_placed_message(self, test_domain):
        identifier = str(uuid4())
        order = Order(id=identifier, customer_id="cust-1", total=99.0)
        order.raise_(OrderPlaced(order_id=identifier, customer_id="cust-1", total=99.0))
        return Message.from_domain_object(order._events[-1])

    @pytest.mark.asyncio
    async def test_pm_transition_emitted_on_success(self, test_domain):
        """handle_message emits pm.transition for process managers, with a
        duration and the PM's own stream category. The trace reaches the
        trace stream when nobody is listening live."""
        engine = Engine(domain=test_domain, test_mode=True)
        traces = _record_traces(engine, persist=True)

        message = self._make_order_placed_message(test_domain)
        result = await engine.handle_message(OrderFulfillmentPM, message)

        assert result is True

        pm_traces = _traces(traces, "pm.transition")
        assert len(pm_traces) == 1
        trace = pm_traces[0]
        assert trace["handler"] == "OrderFulfillmentPM"
        assert trace["message_type"] is not None
        assert trace["duration_ms"] >= 0
        assert trace["metadata"]["pm_type"] == "OrderFulfillmentPM"
        assert trace["metadata"]["pm_stream_category"] is not None

    @pytest.mark.asyncio
    async def test_pm_transition_not_emitted_for_regular_handler(self, test_domain):
        """Regular event handlers do NOT emit pm.transition."""
        # Register a regular event handler next to the process manager
        test_domain.register(User, event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(domain=test_domain, test_mode=True)
        traces = _record_traces(engine)

        message = _make_event_message(test_domain)
        await engine.handle_message(UserEventHandler, message)

        assert len(_traces(traces, "handler.completed")) == 1
        assert _traces(traces, "pm.transition") == []


class TestShutdownInFlight:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User, event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.mark.asyncio
    async def test_runs_and_traces_when_shutting_down(self, test_domain):
        """A message already in a batch is handled and traced during shutdown."""
        engine = Engine(domain=test_domain, test_mode=True)
        traces = _record_traces(engine)
        engine.shutting_down = True

        message = _make_event_message(test_domain)
        result = await engine.handle_message(UserEventHandler, message)

        assert result is True
        assert len(_traces(traces, "handler.completed")) == 1
        assert len(handler_calls) == 1
