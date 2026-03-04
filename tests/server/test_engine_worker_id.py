"""Tests that worker_id flows through Engine.handle_message() to trace emissions.

Uses real Protean elements and real Redis to verify end-to-end worker_id propagation.
"""

import json
from uuid import uuid4

import pytest

from protean import apply
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.domain import Domain
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.tracing import TRACE_CHANNEL, TRACE_STREAM
from protean.utils.eventing import Message
from protean.utils.mixins import handle
from tests.shared import REDIS_URI


# --- Domain elements ---


class OrderPlaced(BaseEvent):
    order_id = Identifier()
    customer = String()


class FailingOrderPlaced(BaseEvent):
    order_id = Identifier()


class Order(BaseAggregate):
    customer = String()

    @apply
    def on_placed(self, event: OrderPlaced) -> None:
        self.customer = event.customer

    @apply
    def on_failing_placed(self, event: FailingOrderPlaced) -> None:
        pass  # No-op; event exists only to test handler failure


handler_invocations: list = []


class OrderNotificationHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def notify(self, event: OrderPlaced) -> None:
        handler_invocations.append(event.order_id)


class FailingHandler(BaseEventHandler):
    @handle(FailingOrderPlaced)
    def handle(self, event: FailingOrderPlaced) -> None:
        raise RuntimeError("Intentional test failure")


# --- Fixtures ---


@pytest.fixture(autouse=True)
def test_domain(request):
    """Create a Redis-backed domain for engine worker_id tests."""
    domain = Domain(name="EngineWorkerIdTests")
    domain.config["brokers"]["default"] = {
        "provider": "redis",
        "URI": f"{REDIS_URI}/2",
    }
    domain.config["command_processing"] = "sync"
    domain.config["event_processing"] = "sync"
    domain._initialize()

    domain.register(Order, is_event_sourced=True)
    domain.register(OrderPlaced, part_of=Order)
    domain.register(FailingOrderPlaced, part_of=Order)
    domain.register(OrderNotificationHandler, part_of=Order)
    domain.register(FailingHandler, part_of=Order)
    domain.init(traverse=False)

    with domain.domain_context():
        yield domain


@pytest.fixture(autouse=True)
def reset_state():
    handler_invocations.clear()
    yield


@pytest.fixture
def engine(test_domain):
    return Engine(domain=test_domain, test_mode=True)


def _make_message() -> Message:
    """Create a real Message from a domain event."""
    order_id = str(uuid4())
    order = Order(id=order_id, customer="Alice")
    order.raise_(OrderPlaced(order_id=order_id, customer="Alice"))
    return Message.from_domain_object(order._events[-1])


# --- Tests ---


@pytest.mark.no_test_domain
@pytest.mark.redis
@pytest.mark.asyncio
async def test_handle_message_passes_worker_id_to_traces(test_domain, engine):
    """worker_id is included in traces emitted during handle_message()."""
    emitter = engine.emitter
    emitter._ensure_initialized()

    # Clean the trace stream
    emitter._redis.delete(TRACE_STREAM)

    # Force persistence so traces land in the stream
    emitter._persist = True

    message = _make_message()
    worker_id = "OrderNotificationHandler-testhost-42-aabbcc"

    await engine.handle_message(OrderNotificationHandler, message, worker_id=worker_id)

    # Verify handler was invoked
    assert len(handler_invocations) == 1

    # Read traces from the stream
    entries = emitter._redis.xrange(TRACE_STREAM)
    traces = []
    for _, fields in entries:
        data_raw = fields.get(b"data") or fields.get("data")
        if isinstance(data_raw, bytes):
            data_raw = data_raw.decode("utf-8")
        traces.append(json.loads(data_raw))

    # Should have handler.started and handler.completed
    started = [t for t in traces if t["event"] == "handler.started"]
    completed = [t for t in traces if t["event"] == "handler.completed"]
    assert len(started) >= 1
    assert len(completed) >= 1

    # Both should carry the worker_id
    assert started[-1]["worker_id"] == worker_id
    assert completed[-1]["worker_id"] == worker_id


@pytest.mark.no_test_domain
@pytest.mark.redis
@pytest.mark.asyncio
async def test_handle_message_worker_id_defaults_to_none(test_domain, engine):
    """When worker_id is not passed, traces have worker_id=None."""
    emitter = engine.emitter
    emitter._ensure_initialized()

    emitter._redis.delete(TRACE_STREAM)
    emitter._persist = True

    message = _make_message()

    await engine.handle_message(OrderNotificationHandler, message)

    entries = emitter._redis.xrange(TRACE_STREAM)
    traces = []
    for _, fields in entries:
        data_raw = fields.get(b"data") or fields.get("data")
        if isinstance(data_raw, bytes):
            data_raw = data_raw.decode("utf-8")
        traces.append(json.loads(data_raw))

    completed = [t for t in traces if t["event"] == "handler.completed"]
    assert len(completed) >= 1
    assert completed[-1]["worker_id"] is None


@pytest.mark.no_test_domain
@pytest.mark.redis
@pytest.mark.asyncio
async def test_handle_message_worker_id_in_pubsub(test_domain, engine):
    """worker_id appears in the Pub/Sub message when a subscriber is listening."""
    emitter = engine.emitter
    emitter._ensure_initialized()

    # Subscribe to trace channel
    pubsub = emitter._redis.pubsub()
    pubsub.subscribe(TRACE_CHANNEL)
    pubsub.get_message(timeout=1.0)  # Consume subscription confirmation

    try:
        # Force emitter to see the subscriber
        emitter._last_subscriber_check = 0.0

        message = _make_message()
        worker_id = "OrderNotificationHandler-pubhost-99-112233"

        await engine.handle_message(
            OrderNotificationHandler, message, worker_id=worker_id
        )

        # Collect all published traces
        received = []
        for _ in range(10):
            msg = pubsub.get_message(timeout=1.0)
            if msg and msg["type"] == "message":
                received.append(json.loads(msg["data"]))

        # At least handler.started and handler.completed should be published
        assert len(received) >= 2
        for trace in received:
            assert trace["worker_id"] == worker_id
    finally:
        pubsub.unsubscribe(TRACE_CHANNEL)
        pubsub.close()


@pytest.mark.no_test_domain
@pytest.mark.redis
@pytest.mark.asyncio
async def test_failed_handler_traces_include_worker_id(test_domain):
    """worker_id is included in handler.failed traces when processing fails."""
    engine = Engine(domain=test_domain, test_mode=True)
    emitter = engine.emitter
    emitter._ensure_initialized()

    emitter._redis.delete(TRACE_STREAM)
    emitter._persist = True

    order_id = str(uuid4())
    order = Order(id=order_id, customer="Bob")
    order.raise_(FailingOrderPlaced(order_id=order_id))
    message = Message.from_domain_object(order._events[-1])

    worker_id = "FailingHandler-failhost-77-deadbe"
    result = await engine.handle_message(FailingHandler, message, worker_id=worker_id)
    assert result is False  # Handler failed

    entries = emitter._redis.xrange(TRACE_STREAM)
    traces = []
    for _, fields in entries:
        data_raw = fields.get(b"data") or fields.get("data")
        if isinstance(data_raw, bytes):
            data_raw = data_raw.decode("utf-8")
        traces.append(json.loads(data_raw))

    failed = [t for t in traces if t["event"] == "handler.failed"]
    assert len(failed) >= 1
    assert failed[-1]["worker_id"] == worker_id
    assert failed[-1]["status"] == "error"
    assert "Intentional test failure" in failed[-1]["error"]
