"""Tests for correlation_id bridging from external broker messages to subscribers.

Verifies that:
1. External message with correlation_id in metadata -> subscriber-triggered
   commands inherit it.
2. External message with no correlation_id -> auto-generated, consistent
   within the subscriber call.
3. causation_id on subscriber-triggered commands = stub message's headers.id.
4. Multiple domain.process() calls in one subscriber handler share the
   same correlation_id.
"""

from uuid import uuid4

import pytest

from protean.core.subscriber import BaseSubscriber
from protean.server import Engine
from protean.utils.eventing import Message
from protean.utils.globals import g

from tests.tracing.elements import (
    ConfirmOrder,
    Order,
    OrderCommandHandler,
    OrderConfirmed,
    OrderPlaced,
    OrderShipped,
    PlaceOrder,
    ShipOrder,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _register_and_init(test_domain, subscriber_cls, stream: str = "external_orders"):
    """Register domain elements needed for the subscriber correlation tests."""
    test_domain.register(Order, is_event_sourced=True)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.register(OrderConfirmed, part_of=Order)
    test_domain.register(OrderShipped, part_of=Order)
    test_domain.register(PlaceOrder, part_of=Order)
    test_domain.register(ConfirmOrder, part_of=Order)
    test_domain.register(ShipOrder, part_of=Order)
    test_domain.register(OrderCommandHandler, part_of=Order)
    test_domain.register(subscriber_cls, stream=stream)
    test_domain.init(traverse=False)


def _read_commands(test_domain, order_id: str) -> list[Message]:
    stream = f"{Order.meta_.stream_category}:command-{order_id}"
    return test_domain.event_store.store.read(stream)


def _read_events(test_domain, order_id: str) -> list[Message]:
    stream = f"{Order.meta_.stream_category}-{order_id}"
    return test_domain.event_store.store.read(stream)


def _external_message_with_correlation(
    order_id: str, customer: str, amount: float, correlation_id: str
) -> dict:
    """Build a dict resembling Protean's external message format."""
    return {
        "data": {
            "order_id": order_id,
            "customer": customer,
            "amount": amount,
        },
        "metadata": {
            "domain": {
                "correlation_id": correlation_id,
            },
        },
    }


def _external_message_without_correlation(
    order_id: str, customer: str, amount: float
) -> dict:
    """Build a plain dict with no Protean metadata (foreign system message)."""
    return {
        "order_id": order_id,
        "customer": customer,
        "amount": amount,
    }


# ---------------------------------------------------------------------------
# Subscribers
# ---------------------------------------------------------------------------
class PlaceOrderSubscriber(BaseSubscriber):
    """Subscriber that places an order from an external broker message."""

    def __call__(self, data: dict) -> None:
        from protean.utils.globals import current_domain

        # Handle both Protean external format and plain dicts
        payload = data.get("data", data)
        current_domain.process(
            PlaceOrder(
                order_id=payload["order_id"],
                customer=payload["customer"],
                amount=payload["amount"],
            ),
            asynchronous=False,
        )


class MultiCommandSubscriber(BaseSubscriber):
    """Subscriber that dispatches multiple commands from a single message."""

    def __call__(self, data: dict) -> None:
        from protean.utils.globals import current_domain

        payload = data.get("data", data)
        current_domain.process(
            PlaceOrder(
                order_id=payload["order_id"],
                customer=payload["customer"],
                amount=payload["amount"],
            ),
            asynchronous=False,
        )
        current_domain.process(
            ConfirmOrder(order_id=payload["order_id"]),
            asynchronous=False,
        )


# Store captured correlation IDs from g.message_in_context
_captured: list[dict] = []


class CorrelationCapturingSubscriber(BaseSubscriber):
    """Subscriber that captures the correlation_id from message context."""

    def __call__(self, data: dict) -> None:
        ctx = g.get("message_in_context")
        if ctx is not None:
            _captured.append(
                {
                    "correlation_id": ctx.metadata.domain.correlation_id,
                    "message_id": ctx.metadata.headers.id,
                }
            )


@pytest.fixture(autouse=True)
def clear_captured():
    yield
    _captured.clear()


# ---------------------------------------------------------------------------
# Tests: External message WITH correlation_id
# ---------------------------------------------------------------------------
class TestExternalCorrelationIdBridging:
    @pytest.mark.asyncio
    @pytest.mark.eventstore
    async def test_correlation_id_from_external_message_flows_to_command(
        self, test_domain
    ):
        """External message with correlation_id -> subscriber-triggered command
        inherits it."""
        _register_and_init(test_domain, PlaceOrderSubscriber)
        engine = Engine(domain=test_domain, test_mode=True)

        order_id = str(uuid4())
        ext_corr_id = "upstream-service-corr-001"
        message = _external_message_with_correlation(
            order_id, "Alice", 99.0, ext_corr_id
        )

        result = await engine.handle_broker_message(
            PlaceOrderSubscriber,
            message,
            message_id="broker-msg-100",
            stream="external_orders",
        )
        assert result is True

        commands = _read_commands(test_domain, order_id)
        assert len(commands) >= 1
        assert commands[0].metadata.domain.correlation_id == ext_corr_id

    @pytest.mark.asyncio
    @pytest.mark.eventstore
    async def test_correlation_id_from_external_message_flows_to_events(
        self, test_domain
    ):
        """External correlation_id propagates through commands to events."""
        _register_and_init(test_domain, PlaceOrderSubscriber)
        engine = Engine(domain=test_domain, test_mode=True)

        order_id = str(uuid4())
        ext_corr_id = "upstream-service-corr-002"
        message = _external_message_with_correlation(
            order_id, "Bob", 150.0, ext_corr_id
        )

        await engine.handle_broker_message(
            PlaceOrderSubscriber,
            message,
            message_id="broker-msg-200",
            stream="external_orders",
        )

        events = _read_events(test_domain, order_id)
        assert len(events) >= 1
        for evt in events:
            assert evt.metadata.domain.correlation_id == ext_corr_id

    @pytest.mark.asyncio
    async def test_correlation_id_set_on_stub_message_context(self, test_domain):
        """The stub message in g.message_in_context carries the extracted
        correlation_id."""
        _register_and_init(test_domain, CorrelationCapturingSubscriber)
        engine = Engine(domain=test_domain, test_mode=True)

        ext_corr_id = "upstream-corr-ctx-test"
        message = _external_message_with_correlation(
            str(uuid4()), "Carol", 50.0, ext_corr_id
        )

        await engine.handle_broker_message(
            CorrelationCapturingSubscriber,
            message,
            message_id="broker-msg-300",
            stream="external_orders",
        )

        assert len(_captured) == 1
        assert _captured[0]["correlation_id"] == ext_corr_id


# ---------------------------------------------------------------------------
# Tests: External message WITHOUT correlation_id
# ---------------------------------------------------------------------------
class TestAutoGeneratedCorrelationIdForBrokerMessages:
    @pytest.mark.asyncio
    @pytest.mark.eventstore
    async def test_auto_generated_when_no_correlation_in_message(self, test_domain):
        """When the external message has no correlation_id, a fresh one is
        auto-generated and used."""
        _register_and_init(test_domain, PlaceOrderSubscriber)
        engine = Engine(domain=test_domain, test_mode=True)

        order_id = str(uuid4())
        message = _external_message_without_correlation(order_id, "Dave", 200.0)

        await engine.handle_broker_message(
            PlaceOrderSubscriber,
            message,
            message_id="broker-msg-400",
            stream="external_orders",
        )

        commands = _read_commands(test_domain, order_id)
        assert len(commands) >= 1
        corr_id = commands[0].metadata.domain.correlation_id
        assert corr_id is not None
        assert isinstance(corr_id, str)
        assert len(corr_id) > 0

    @pytest.mark.asyncio
    async def test_auto_generated_correlation_on_context(self, test_domain):
        """When no correlation_id in message, stub context still has one."""
        _register_and_init(test_domain, CorrelationCapturingSubscriber)
        engine = Engine(domain=test_domain, test_mode=True)

        message = _external_message_without_correlation(str(uuid4()), "Eve", 75.0)

        await engine.handle_broker_message(
            CorrelationCapturingSubscriber,
            message,
            message_id="broker-msg-500",
            stream="external_orders",
        )

        assert len(_captured) == 1
        assert _captured[0]["correlation_id"] is not None
        assert len(_captured[0]["correlation_id"]) > 0

    @pytest.mark.asyncio
    async def test_auto_generated_ids_differ_across_messages(self, test_domain):
        """Each broker message without correlation_id gets a unique auto-generated ID."""
        _register_and_init(test_domain, CorrelationCapturingSubscriber)
        engine = Engine(domain=test_domain, test_mode=True)

        for i in range(3):
            message = _external_message_without_correlation(
                str(uuid4()), f"User{i}", 10.0
            )
            await engine.handle_broker_message(
                CorrelationCapturingSubscriber,
                message,
                message_id=f"broker-msg-60{i}",
                stream="external_orders",
            )

        assert len(_captured) == 3
        corr_ids = {c["correlation_id"] for c in _captured}
        assert len(corr_ids) == 3, "Each message should get a unique correlation_id"


# ---------------------------------------------------------------------------
# Tests: Causation chain
# ---------------------------------------------------------------------------
class TestCausationIdFromBrokerMessage:
    @pytest.mark.asyncio
    @pytest.mark.eventstore
    async def test_causation_id_is_stub_message_id(self, test_domain):
        """Commands triggered by a subscriber have causation_id = stub message's
        headers.id (the broker-assigned message identifier)."""
        _register_and_init(test_domain, PlaceOrderSubscriber)
        engine = Engine(domain=test_domain, test_mode=True)

        order_id = str(uuid4())
        broker_msg_id = "broker-assigned-id-789"
        message = _external_message_with_correlation(
            order_id, "Frank", 300.0, "corr-for-causation"
        )

        await engine.handle_broker_message(
            PlaceOrderSubscriber,
            message,
            message_id=broker_msg_id,
            stream="external_orders",
        )

        commands = _read_commands(test_domain, order_id)
        assert len(commands) >= 1
        assert commands[0].metadata.domain.causation_id == broker_msg_id


# ---------------------------------------------------------------------------
# Tests: Multiple domain.process() calls in one subscriber
# ---------------------------------------------------------------------------
class TestMultipleProcessCallsShareCorrelation:
    @pytest.mark.asyncio
    @pytest.mark.eventstore
    async def test_multiple_commands_share_correlation_id(self, test_domain):
        """Multiple domain.process() calls within a single subscriber handler
        all inherit the same correlation_id from the broker message."""
        _register_and_init(test_domain, MultiCommandSubscriber)
        engine = Engine(domain=test_domain, test_mode=True)

        order_id = str(uuid4())
        ext_corr_id = "multi-cmd-corr-001"
        message = _external_message_with_correlation(
            order_id, "Grace", 500.0, ext_corr_id
        )

        result = await engine.handle_broker_message(
            MultiCommandSubscriber,
            message,
            message_id="broker-msg-700",
            stream="external_orders",
        )
        assert result is True

        # Both the PlaceOrder and ConfirmOrder commands should share correlation
        place_commands = _read_commands(test_domain, order_id)
        assert len(place_commands) >= 1
        assert place_commands[0].metadata.domain.correlation_id == ext_corr_id

        # Events from both commands should also share correlation
        events = _read_events(test_domain, order_id)
        assert len(events) >= 2
        for evt in events:
            assert evt.metadata.domain.correlation_id == ext_corr_id

    @pytest.mark.asyncio
    @pytest.mark.eventstore
    async def test_multiple_commands_auto_gen_share_same_correlation(self, test_domain):
        """Multiple domain.process() calls without explicit correlation_id
        all share the same auto-generated correlation_id."""
        _register_and_init(test_domain, MultiCommandSubscriber)
        engine = Engine(domain=test_domain, test_mode=True)

        order_id = str(uuid4())
        message = _external_message_without_correlation(order_id, "Hank", 250.0)

        await engine.handle_broker_message(
            MultiCommandSubscriber,
            message,
            message_id="broker-msg-800",
            stream="external_orders",
        )

        # Both commands should share the same auto-generated correlation_id
        place_commands = _read_commands(test_domain, order_id)
        assert len(place_commands) >= 1
        auto_corr_id = place_commands[0].metadata.domain.correlation_id
        assert auto_corr_id is not None

        events = _read_events(test_domain, order_id)
        assert len(events) >= 2
        for evt in events:
            assert evt.metadata.domain.correlation_id == auto_corr_id


# ---------------------------------------------------------------------------
# Tests: _extract_correlation_id helper
# ---------------------------------------------------------------------------
class TestExtractCorrelationIdHelper:
    """Unit tests for the _extract_correlation_id helper function."""

    def test_extracts_from_protean_external_format(self):
        from protean.server.engine import _extract_correlation_id

        msg = {
            "data": {"foo": "bar"},
            "metadata": {
                "domain": {"correlation_id": "ext-corr-123"},
            },
        }
        assert _extract_correlation_id(msg) == "ext-corr-123"

    def test_generates_new_when_no_metadata_key(self):
        from protean.server.engine import _extract_correlation_id

        msg = {"data": {"foo": "bar"}}
        result = _extract_correlation_id(msg)
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generates_new_when_correlation_is_none(self):
        from protean.server.engine import _extract_correlation_id

        msg = {
            "metadata": {
                "domain": {"correlation_id": None},
            },
        }
        result = _extract_correlation_id(msg)
        assert result is not None
        assert len(result) > 0

    def test_generates_new_for_empty_dict(self):
        from protean.server.engine import _extract_correlation_id

        result = _extract_correlation_id({})
        assert result is not None
        assert len(result) > 0

    def test_generates_new_when_domain_missing(self):
        from protean.server.engine import _extract_correlation_id

        msg = {"metadata": {"headers": {"id": "msg-1"}}}
        result = _extract_correlation_id(msg)
        assert result is not None
        assert len(result) > 0

    def test_generates_unique_ids(self):
        from protean.server.engine import _extract_correlation_id

        ids = {_extract_correlation_id({}) for _ in range(10)}
        assert len(ids) == 10

    def test_coerces_non_string_to_string(self):
        from protean.server.engine import _extract_correlation_id

        msg = {
            "metadata": {
                "domain": {"correlation_id": 12345},
            },
        }
        result = _extract_correlation_id(msg)
        assert result == "12345"

    def test_extracts_from_metadata_correlation_id(self):
        from protean.server.engine import _extract_correlation_id

        msg = {
            "data": {"foo": "bar"},
            "metadata": {"correlation_id": "meta-corr-456"},
        }
        assert _extract_correlation_id(msg) == "meta-corr-456"

    def test_extracts_from_top_level_correlation_id(self):
        from protean.server.engine import _extract_correlation_id

        msg = {"data": {"foo": "bar"}, "correlation_id": "top-corr-789"}
        assert _extract_correlation_id(msg) == "top-corr-789"

    def test_prefers_metadata_domain_over_metadata(self):
        from protean.server.engine import _extract_correlation_id

        msg = {
            "metadata": {
                "domain": {"correlation_id": "deep"},
                "correlation_id": "shallow",
            },
            "correlation_id": "top",
        }
        assert _extract_correlation_id(msg) == "deep"

    def test_falls_back_from_metadata_domain_to_metadata(self):
        from protean.server.engine import _extract_correlation_id

        msg = {
            "metadata": {"correlation_id": "shallow"},
            "correlation_id": "top",
        }
        assert _extract_correlation_id(msg) == "shallow"

    def test_generates_new_for_empty_string(self):
        from protean.server.engine import _extract_correlation_id

        msg = {"metadata": {"domain": {"correlation_id": ""}}}
        result = _extract_correlation_id(msg)
        assert result != ""
        assert len(result) > 0

    def test_generates_new_for_whitespace_only(self):
        from protean.server.engine import _extract_correlation_id

        msg = {"metadata": {"domain": {"correlation_id": "   "}}}
        result = _extract_correlation_id(msg)
        assert result.strip() != ""

    def test_skips_blank_and_falls_back(self):
        from protean.server.engine import _extract_correlation_id

        msg = {
            "metadata": {
                "domain": {"correlation_id": "  "},
                "correlation_id": "valid-fallback",
            },
        }
        assert _extract_correlation_id(msg) == "valid-fallback"
