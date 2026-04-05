"""Tests for Engine.handle_broker_message.

Covers the async broker message handling path: shutdown guard, success
and failure flows, message_in_context lifecycle, and source message_id
extraction from broker payloads.
"""

import pytest

from protean.core.subscriber import BaseSubscriber
from protean.domain import Processing
from protean.server import Engine
from protean.server.engine import _extract_source_message_id
from protean.utils.eventing import Message
from protean.utils.globals import g


# ---------------------------------------------------------------------------
# Module-level state captured by test subscribers
# ---------------------------------------------------------------------------
_call_log: list[dict] = []
_captured_contexts: list[Message | None] = []


class SuccessSubscriber(BaseSubscriber):
    """Subscriber that succeeds and records calls."""

    def __call__(self, data: dict) -> None:
        _call_log.append(data)


class ContextCapturingSubscriber(BaseSubscriber):
    """Subscriber that captures g.message_in_context during processing."""

    def __call__(self, data: dict) -> None:
        _captured_contexts.append(g.get("message_in_context"))


class FailingSubscriber(BaseSubscriber):
    """Subscriber whose __call__ always raises."""

    def __call__(self, data: dict) -> None:
        _captured_contexts.append(g.get("message_in_context"))
        raise RuntimeError("intentional failure")


class FailingErrorHandlerSubscriber(BaseSubscriber):
    """Subscriber whose handle_error also raises."""

    def __call__(self, data: dict) -> None:
        raise ValueError("primary failure")

    @classmethod
    def handle_error(cls, exc: Exception, message: dict) -> None:
        raise RuntimeError("error handler failure")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clear_state():
    """Reset module-level state between tests."""
    yield
    _call_log.clear()
    _captured_contexts.clear()


@pytest.fixture(autouse=True)
def _set_async_processing(test_domain):
    """Broker message tests need async message_processing."""
    test_domain.config["message_processing"] = Processing.ASYNC.value


def _register_and_init(test_domain, subscriber_cls, stream: str = "test_stream"):
    """Helper to register a subscriber and init the domain."""
    test_domain.register(subscriber_cls, stream=stream)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# 1. Returns False when shutting_down is True
# ---------------------------------------------------------------------------
class TestShuttingDown:
    @pytest.mark.asyncio
    async def test_returns_false_when_shutting_down(self, test_domain):
        _register_and_init(test_domain, SuccessSubscriber)
        engine = Engine(domain=test_domain, test_mode=True)
        engine.shutting_down = True

        result = await engine.handle_broker_message(SuccessSubscriber, {"key": "value"})
        assert result is False
        assert len(_call_log) == 0


# ---------------------------------------------------------------------------
# 2. Returns True on successful processing
# ---------------------------------------------------------------------------
class TestSuccessfulProcessing:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self, test_domain):
        _register_and_init(test_domain, SuccessSubscriber)
        engine = Engine(domain=test_domain, test_mode=True)

        result = await engine.handle_broker_message(SuccessSubscriber, {"foo": "bar"})
        assert result is True
        assert _call_log == [{"foo": "bar"}]


# ---------------------------------------------------------------------------
# 3. Returns False on subscriber exception
# ---------------------------------------------------------------------------
class TestSubscriberException:
    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self, test_domain):
        _register_and_init(test_domain, FailingSubscriber, stream="fail_stream")
        engine = Engine(domain=test_domain, test_mode=True)

        result = await engine.handle_broker_message(FailingSubscriber, {"foo": "bar"})
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_error_handler_also_fails(self, test_domain):
        """Engine handles double failure (subscriber + error handler) gracefully."""
        _register_and_init(
            test_domain, FailingErrorHandlerSubscriber, stream="double_fail"
        )
        engine = Engine(domain=test_domain, test_mode=True)

        result = await engine.handle_broker_message(
            FailingErrorHandlerSubscriber, {"key": "value"}
        )
        assert result is False


# ---------------------------------------------------------------------------
# 4. Sets message_in_context when message_id and stream are provided
# ---------------------------------------------------------------------------
class TestMessageInContextSet:
    @pytest.mark.asyncio
    async def test_message_in_context_available_during_processing(self, test_domain):
        _register_and_init(test_domain, ContextCapturingSubscriber, stream="ctx_stream")
        engine = Engine(domain=test_domain, test_mode=True)

        await engine.handle_broker_message(
            ContextCapturingSubscriber,
            {"key": "value"},
            message_id="msg-100",
            stream="ctx_stream",
        )

        assert len(_captured_contexts) == 1
        msg = _captured_contexts[0]
        assert isinstance(msg, Message)
        assert msg.metadata.headers.id == "msg-100"
        assert msg.metadata.headers.stream == "ctx_stream"
        assert msg.metadata.domain.kind == "BROKER_MESSAGE"
        assert msg.data == {"key": "value"}

    @pytest.mark.asyncio
    async def test_no_context_when_metadata_not_provided(self, test_domain):
        """When message_id and stream are omitted, no context is set."""
        _register_and_init(test_domain, ContextCapturingSubscriber, stream="ctx_stream")
        engine = Engine(domain=test_domain, test_mode=True)

        await engine.handle_broker_message(ContextCapturingSubscriber, {"key": "value"})

        assert len(_captured_contexts) == 1
        assert _captured_contexts[0] is None

    @pytest.mark.asyncio
    async def test_no_context_when_only_message_id_provided(self, test_domain):
        """Both message_id AND stream are needed; one alone is not enough."""
        _register_and_init(test_domain, ContextCapturingSubscriber, stream="ctx_stream")
        engine = Engine(domain=test_domain, test_mode=True)

        await engine.handle_broker_message(
            ContextCapturingSubscriber,
            {"key": "value"},
            message_id="msg-200",
        )

        assert len(_captured_contexts) == 1
        assert _captured_contexts[0] is None


# ---------------------------------------------------------------------------
# 5. Cleans up message_in_context on success
# ---------------------------------------------------------------------------
class TestContextCleanupOnSuccess:
    @pytest.mark.asyncio
    async def test_context_cleaned_up_after_success(self, test_domain):
        _register_and_init(test_domain, ContextCapturingSubscriber, stream="ctx_stream")
        engine = Engine(domain=test_domain, test_mode=True)

        with test_domain.domain_context():
            await engine.handle_broker_message(
                ContextCapturingSubscriber,
                {"key": "value"},
                message_id="msg-300",
                stream="ctx_stream",
            )
            # After the call, the context should have been cleaned up
            assert g.get("message_in_context") is None


# ---------------------------------------------------------------------------
# 6. Cleans up message_in_context on failure
# ---------------------------------------------------------------------------
class TestContextCleanupOnFailure:
    @pytest.mark.asyncio
    async def test_context_cleaned_up_after_failure(self, test_domain):
        _register_and_init(test_domain, FailingSubscriber, stream="fail_stream")
        engine = Engine(domain=test_domain, test_mode=True)

        with test_domain.domain_context():
            result = await engine.handle_broker_message(
                FailingSubscriber,
                {"key": "value"},
                message_id="msg-400",
                stream="fail_stream",
            )
            assert result is False
            # Context was available inside the subscriber
            assert _captured_contexts[0] is not None
            assert _captured_contexts[0].metadata.headers.id == "msg-400"
            # But cleaned up after the call
            assert g.get("message_in_context") is None


# ---------------------------------------------------------------------------
# 7. _extract_source_message_id unit tests
# ---------------------------------------------------------------------------
class TestExtractSourceMessageId:
    def test_extracts_from_protean_message_format(self):
        """Standard Protean broker message has metadata.headers.id."""
        message = {
            "data": {"foo": "bar"},
            "metadata": {
                "headers": {"id": "catalogue::product-6ed888bb-1.1"},
            },
        }
        assert _extract_source_message_id(message) == "catalogue::product-6ed888bb-1.1"

    def test_returns_none_for_missing_metadata(self):
        """Raw external message without metadata."""
        assert _extract_source_message_id({"data": {"foo": "bar"}}) is None

    def test_returns_none_for_missing_headers(self):
        assert _extract_source_message_id({"metadata": {}}) is None

    def test_returns_none_for_missing_id(self):
        assert _extract_source_message_id({"metadata": {"headers": {}}}) is None

    def test_returns_none_for_empty_string_id(self):
        assert _extract_source_message_id({"metadata": {"headers": {"id": ""}}}) is None

    def test_returns_none_for_whitespace_id(self):
        assert (
            _extract_source_message_id({"metadata": {"headers": {"id": "   "}}}) is None
        )

    def test_returns_none_for_none_id(self):
        assert (
            _extract_source_message_id({"metadata": {"headers": {"id": None}}}) is None
        )

    def test_strips_whitespace(self):
        message = {"metadata": {"headers": {"id": "  msg-123  "}}}
        assert _extract_source_message_id(message) == "msg-123"

    def test_returns_none_for_non_string_id(self):
        """Non-string id values are rejected."""
        assert _extract_source_message_id({"metadata": {"headers": {"id": 42}}}) is None


# ---------------------------------------------------------------------------
# 8. Source message_id preferred over broker delivery ID
# ---------------------------------------------------------------------------
class TestSourceMessageIdPreferredOverDeliveryId:
    @pytest.mark.asyncio
    async def test_uses_source_message_id_from_payload(self, test_domain):
        """When payload contains metadata.headers.id, it takes precedence
        over the broker delivery ID for causation_id propagation."""
        _register_and_init(test_domain, ContextCapturingSubscriber, stream="ctx_stream")
        engine = Engine(domain=test_domain, test_mode=True)

        source_event_id = "ordering::order-747b772c-9a-1.1"
        redis_delivery_id = "1775350249700-0"

        await engine.handle_broker_message(
            ContextCapturingSubscriber,
            {
                "data": {"order_id": "123"},
                "metadata": {
                    "headers": {"id": source_event_id, "type": "OrderShipped"},
                    "domain": {"correlation_id": "corr-abc"},
                },
            },
            message_id=redis_delivery_id,
            stream="ctx_stream",
        )

        assert len(_captured_contexts) == 1
        msg = _captured_contexts[0]
        assert isinstance(msg, Message)
        # Source message_id from payload, NOT the Redis delivery ID
        assert msg.metadata.headers.id == source_event_id
        assert msg.metadata.headers.id != redis_delivery_id

    @pytest.mark.asyncio
    async def test_falls_back_to_delivery_id_for_raw_messages(self, test_domain):
        """When payload has no metadata.headers.id (raw external message),
        the broker delivery ID is used as fallback."""
        _register_and_init(test_domain, ContextCapturingSubscriber, stream="ctx_stream")
        engine = Engine(domain=test_domain, test_mode=True)

        redis_delivery_id = "1775350249700-0"

        await engine.handle_broker_message(
            ContextCapturingSubscriber,
            {"raw_field": "external_data"},
            message_id=redis_delivery_id,
            stream="ctx_stream",
        )

        assert len(_captured_contexts) == 1
        msg = _captured_contexts[0]
        assert msg.metadata.headers.id == redis_delivery_id

    @pytest.mark.asyncio
    async def test_falls_back_when_embedded_id_is_empty(self, test_domain):
        """Empty/whitespace metadata.headers.id falls back to delivery ID."""
        _register_and_init(test_domain, ContextCapturingSubscriber, stream="ctx_stream")
        engine = Engine(domain=test_domain, test_mode=True)

        redis_delivery_id = "1775350249700-0"

        await engine.handle_broker_message(
            ContextCapturingSubscriber,
            {"metadata": {"headers": {"id": ""}}},
            message_id=redis_delivery_id,
            stream="ctx_stream",
        )

        assert len(_captured_contexts) == 1
        assert _captured_contexts[0].metadata.headers.id == redis_delivery_id
