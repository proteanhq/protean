import pytest

from protean.core.subscriber import BaseSubscriber
from protean.domain import Processing
from protean.server import Engine
from protean.utils.eventing import Message
from protean.utils.globals import g

terms = []
captured_contexts: list[Message | None] = []


def append_to_terms(term):
    global terms
    terms.append(term)


class DummySubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        append_to_terms(data["foo"])


class ContextCapturingSubscriber(BaseSubscriber):
    """Subscriber that captures g.message_in_context during processing."""

    def __call__(self, data: dict) -> None:
        ctx = g.get("message_in_context")
        captured_contexts.append(ctx)


@pytest.fixture(autouse=True)
def clear_terms():
    yield

    global terms, captured_contexts
    terms = []
    captured_contexts = []


@pytest.fixture(autouse=True)
def set_message_processing_async(test_domain):
    test_domain.config["message_processing"] = Processing.ASYNC.value


def test_processing_broker_messages(test_domain):
    test_domain.register(DummySubscriber, stream="test_stream")
    test_domain.init(traverse=False)

    stream = "test_stream"
    message1 = {"foo": "bar"}
    message2 = {"foo": "baz"}
    test_domain.brokers["default"].publish(stream, message1)
    test_domain.brokers["default"].publish(stream, message2)

    engine = Engine(domain=test_domain, test_mode=True)
    engine.run()

    global terms
    assert len(terms) == 2
    assert terms[0] == "bar"
    assert terms[1] == "baz"


def test_no_processing_when_shutting_down(test_domain):
    test_domain.register(DummySubscriber, stream="test_stream")
    test_domain.init(traverse=False)

    stream = "test_stream"
    message = {"foo": "bar"}
    test_domain.brokers["default"].publish(stream, message)

    engine = Engine(domain=test_domain, test_mode=True)
    engine.shutting_down = True
    engine.run()

    global terms
    assert len(terms) == 0


@pytest.mark.asyncio
async def test_message_in_context_available_during_broker_processing(test_domain):
    """Subscriber can access message_in_context via g during processing."""
    test_domain.register(ContextCapturingSubscriber, stream="ctx_stream")
    test_domain.init(traverse=False)

    engine = Engine(domain=test_domain, test_mode=True)
    await engine.handle_broker_message(
        ContextCapturingSubscriber,
        {"key": "value"},
        message_id="msg-001",
        stream="ctx_stream",
    )

    assert len(captured_contexts) == 1
    msg = captured_contexts[0]
    assert isinstance(msg, Message)
    assert msg.metadata.headers.id == "msg-001"
    assert msg.metadata.headers.stream == "ctx_stream"
    assert msg.metadata.domain.kind == "BROKER_MESSAGE"
    assert msg.data == {"key": "value"}


@pytest.mark.asyncio
async def test_message_in_context_cleaned_up_after_broker_processing(test_domain):
    """message_in_context is removed from g after subscriber completes."""
    test_domain.register(ContextCapturingSubscriber, stream="ctx_stream")
    test_domain.init(traverse=False)

    engine = Engine(domain=test_domain, test_mode=True)

    with test_domain.domain_context():
        await engine.handle_broker_message(
            ContextCapturingSubscriber,
            {"key": "value"},
            message_id="msg-002",
            stream="ctx_stream",
        )
        # After handle_broker_message returns, context should be cleaned up
        assert g.get("message_in_context") is None


@pytest.mark.asyncio
async def test_message_in_context_cleaned_up_on_broker_error(test_domain):
    """message_in_context is cleaned up even when subscriber raises."""

    class FailingSubscriber(BaseSubscriber):
        def __call__(self, data: dict) -> None:
            # Verify context is available before failing
            ctx = g.get("message_in_context")
            captured_contexts.append(ctx)
            raise RuntimeError("intentional failure")

    test_domain.register(FailingSubscriber, stream="fail_stream")
    test_domain.init(traverse=False)

    engine = Engine(domain=test_domain, test_mode=True)

    with test_domain.domain_context():
        result = await engine.handle_broker_message(
            FailingSubscriber,
            {"key": "value"},
            message_id="msg-003",
            stream="fail_stream",
        )
        assert result is False
        # Context was available during processing
        assert captured_contexts[0].metadata.headers.id == "msg-003"
        # But cleaned up after
        assert g.get("message_in_context") is None


@pytest.mark.asyncio
async def test_message_in_context_none_without_metadata(test_domain):
    """When message_id/stream are not provided, no context is set."""
    test_domain.register(ContextCapturingSubscriber, stream="ctx_stream")
    test_domain.init(traverse=False)

    engine = Engine(domain=test_domain, test_mode=True)
    # Call without message_id and stream (backward compatibility)
    await engine.handle_broker_message(
        ContextCapturingSubscriber,
        {"key": "value"},
    )

    assert len(captured_contexts) == 1
    assert captured_contexts[0] is None
