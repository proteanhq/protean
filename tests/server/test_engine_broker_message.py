"""Tests for Engine.handle_broker_message (engine.py lines 386-440).

Covers the async broker message handling path: shutdown guard, success
and failure flows, message_in_context lifecycle.
"""

import pytest

from protean.core.subscriber import BaseSubscriber
from protean.domain import Processing
from protean.server import Engine
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
