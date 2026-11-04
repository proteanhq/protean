"""Tests for Engine.handle_broker_message.

Covers the async broker message handling path: in-flight work on shutdown, success
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
# 1. Shutting down does not reject at the handler: an in-flight message runs
# ---------------------------------------------------------------------------
class TestShuttingDown:
    @pytest.mark.asyncio
    async def test_processes_inflight_message_when_shutting_down(self, test_domain):
        """A message already read into a batch runs to completion on shutdown.

        A False return here would send it down the NACK/retry/DLQ path. The
        drain_timeout cancellation is what cuts a long batch short.
        """
        _register_and_init(test_domain, SuccessSubscriber)
        engine = Engine(domain=test_domain, test_mode=True)
        engine.shutting_down = True

        result = await engine.handle_broker_message(SuccessSubscriber, {"key": "value"})
        assert result is True
        assert _call_log == [{"key": "value"}]


# ---------------------------------------------------------------------------
# 1b. Draining does NOT reject at the handler: an in-flight message must finish
# ---------------------------------------------------------------------------
class TestDraining:
    @pytest.mark.asyncio
    async def test_processes_inflight_message_while_draining(self, test_domain):
        """A message already dispatched must run to completion while draining.

        Draining gates only the poll loops (they stop fetching new batches). The
        handler has no guard, so a message already read into an in-flight batch
        is processed, not failed. If draining rejected
        here, the False return would travel the NACK/retry/DLQ failure path and
        drop the message, violating the "no in-flight message is dropped" rule.
        """
        _register_and_init(test_domain, SuccessSubscriber)
        engine = Engine(domain=test_domain, test_mode=True)
        engine.draining = True

        result = await engine.handle_broker_message(SuccessSubscriber, {"key": "value"})
        assert result is True
        assert _call_log == [{"key": "value"}]


# ---------------------------------------------------------------------------
# 2. Returns True on successful processing
# ---------------------------------------------------------------------------
class TestSuccessfulProcessing:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self, test_domain):
        _register_and_init(test_domain, SuccessSubscriber)
        engine = Engine(domain=test_domain, test_mode=True)
        assert engine.draining is False

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
# 4. Sets message_in_context when message_id and stream are provided, then clears it
# ---------------------------------------------------------------------------
class TestMessageInContextSet:
    @pytest.mark.asyncio
    async def test_message_in_context_available_during_processing(self, test_domain):
        _register_and_init(test_domain, ContextCapturingSubscriber, stream="ctx_stream")
        engine = Engine(domain=test_domain, test_mode=True)

        with test_domain.domain_context():
            await engine.handle_broker_message(
                ContextCapturingSubscriber,
                {"key": "value"},
                message_id="msg-100",
                stream="ctx_stream",
            )
            # After the call, the context has been cleaned up
            assert g.get("message_in_context") is None

        assert len(_captured_contexts) == 1
        msg = _captured_contexts[0]
        assert isinstance(msg, Message)
        assert msg.metadata.headers.id == "msg-100"
        assert msg.metadata.headers.stream == "ctx_stream"
        assert msg.metadata.domain.kind == "BROKER_MESSAGE"
        assert msg.data == {"key": "value"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "metadata",
        [
            pytest.param({}, id="metadata-not-provided"),
            pytest.param({"message_id": "msg-200"}, id="only-message-id-provided"),
        ],
    )
    async def test_no_context_without_both_message_id_and_stream(
        self, test_domain, metadata
    ):
        """Both message_id AND stream are needed; one alone is not enough."""
        _register_and_init(test_domain, ContextCapturingSubscriber, stream="ctx_stream")
        engine = Engine(domain=test_domain, test_mode=True)

        await engine.handle_broker_message(
            ContextCapturingSubscriber, {"key": "value"}, **metadata
        )

        assert len(_captured_contexts) == 1
        assert _captured_contexts[0] is None


# ---------------------------------------------------------------------------
# 5. Cleans up message_in_context on failure
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
# 6. _extract_source_message_id unit tests
# ---------------------------------------------------------------------------
class TestExtractSourceMessageId:
    @pytest.mark.parametrize(
        "message, expected",
        [
            pytest.param(
                {
                    "data": {"foo": "bar"},
                    "metadata": {
                        "headers": {"id": "catalogue::product-6ed888bb-1.1"},
                    },
                },
                "catalogue::product-6ed888bb-1.1",
                id="protean-message-format",
            ),
            pytest.param({"data": {"foo": "bar"}}, None, id="missing-metadata"),
            pytest.param({"metadata": {}}, None, id="missing-headers"),
            pytest.param({"metadata": {"headers": {}}}, None, id="missing-id"),
            pytest.param({"metadata": {"headers": {"id": ""}}}, None, id="empty-id"),
            pytest.param(
                {"metadata": {"headers": {"id": "   "}}}, None, id="whitespace-id"
            ),
            pytest.param({"metadata": {"headers": {"id": None}}}, None, id="none-id"),
            pytest.param(
                {"metadata": {"headers": {"id": "  msg-123  "}}},
                "msg-123",
                id="strips-whitespace",
            ),
            pytest.param(
                {"metadata": {"headers": {"id": 42}}}, None, id="non-string-id"
            ),
        ],
    )
    def test_extract_source_message_id(self, message, expected):
        assert _extract_source_message_id(message) == expected


# ---------------------------------------------------------------------------
# 7. Source message_id preferred over broker delivery ID
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
    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param({"raw_field": "external_data"}, id="raw-external-message"),
            pytest.param({"metadata": {"headers": {"id": ""}}}, id="empty-embedded-id"),
        ],
    )
    async def test_falls_back_to_delivery_id(self, test_domain, payload):
        """When the payload carries no usable metadata.headers.id, the broker
        delivery ID is used as fallback."""
        _register_and_init(test_domain, ContextCapturingSubscriber, stream="ctx_stream")
        engine = Engine(domain=test_domain, test_mode=True)

        redis_delivery_id = "1775350249700-0"

        await engine.handle_broker_message(
            ContextCapturingSubscriber,
            payload,
            message_id=redis_delivery_id,
            stream="ctx_stream",
        )

        assert len(_captured_contexts) == 1
        assert _captured_contexts[0].metadata.headers.id == redis_delivery_id
