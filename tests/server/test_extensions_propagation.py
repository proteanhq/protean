"""Tests for metadata.extensions propagation into domain context globals.

When the server processes async messages (events/commands), metadata extensions
set by enrichers during the original request should be available in `g` so that
handlers see the same context (tenant_id, user_id, etc.) as the original caller.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean import apply
from protean.fields import Identifier, String
from protean.server import Engine
from protean.utils.eventing import (
    Message,
    Metadata,
)
from protean.utils.globals import g
from protean.utils.mixins import handle


# --- Domain elements for testing ---


class UserRegistered(BaseEvent):
    user_id = Identifier()
    email = String()


class User(BaseAggregate):
    email = String()

    @apply
    def on_registered(self, event: UserRegistered) -> None:
        self.email = event.email


# Captured g attributes during handler execution
captured_g_attrs: list[dict] = []


class ExtensionCapturingHandler(BaseEventHandler):
    """Event handler that captures g attributes during execution."""

    @handle(UserRegistered)
    def on_registered(self, event: UserRegistered) -> None:
        captured_g_attrs.append(
            {
                "tenant_id": g.get("tenant_id"),
                "user_id": g.get("user_id"),
                "request_id": g.get("request_id"),
                "message_in_context": g.get("message_in_context"),
            }
        )


# --- Fixtures ---


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(ExtensionCapturingHandler, part_of=User)
    test_domain.init(traverse=False)


@pytest.fixture(autouse=True)
def reset_captured():
    yield
    captured_g_attrs.clear()


# --- Helpers ---


def _make_message_with_extensions(
    extensions: dict | None = None,
) -> Message:
    """Build a Message for UserRegistered with the given metadata extensions."""
    user_id = str(uuid4())
    user = User(id=user_id, email="test@example.com")
    user.raise_(UserRegistered(user_id=user_id, email="test@example.com"))

    event = user._events[-1]
    message = Message.from_domain_object(event)

    if extensions is not None:
        # Reconstruct metadata with custom extensions
        message = Message(
            data=message.data,
            metadata=Metadata(
                headers=message.metadata.headers,
                envelope=message.metadata.envelope,
                domain=message.metadata.domain,
                event_store=message.metadata.event_store,
                extensions=extensions,
            ),
        )

    return message


# --- Tests ---


@pytest.mark.asyncio
async def test_extensions_available_as_g_attributes(test_domain):
    """Extensions from message metadata are set as g attributes during handler execution."""
    message = _make_message_with_extensions(
        {"tenant_id": "acme-corp", "user_id": "user-42", "request_id": "req-abc"}
    )

    engine = Engine(domain=test_domain, test_mode=True)
    result = await engine.handle_message(ExtensionCapturingHandler, message)

    assert result is True
    assert len(captured_g_attrs) == 1
    assert captured_g_attrs[0]["tenant_id"] == "acme-corp"
    assert captured_g_attrs[0]["user_id"] == "user-42"
    assert captured_g_attrs[0]["request_id"] == "req-abc"


@pytest.mark.asyncio
async def test_message_in_context_still_set_alongside_extensions(test_domain):
    """g.message_in_context is set correctly even when extensions are propagated."""
    message = _make_message_with_extensions({"tenant_id": "acme-corp"})

    engine = Engine(domain=test_domain, test_mode=True)
    await engine.handle_message(ExtensionCapturingHandler, message)

    assert len(captured_g_attrs) == 1
    msg_ctx = captured_g_attrs[0]["message_in_context"]
    assert isinstance(msg_ctx, Message)
    assert msg_ctx.metadata.extensions["tenant_id"] == "acme-corp"


@pytest.mark.asyncio
async def test_empty_extensions_no_issue(test_domain):
    """Empty extensions dict does not cause errors."""
    message = _make_message_with_extensions({})

    engine = Engine(domain=test_domain, test_mode=True)
    result = await engine.handle_message(ExtensionCapturingHandler, message)

    assert result is True
    assert len(captured_g_attrs) == 1
    assert captured_g_attrs[0]["tenant_id"] is None


@pytest.mark.asyncio
async def test_no_extensions_no_issue(test_domain):
    """Message without extensions (default empty dict) works fine."""
    message = _make_message_with_extensions()  # No custom extensions

    engine = Engine(domain=test_domain, test_mode=True)
    result = await engine.handle_message(ExtensionCapturingHandler, message)

    assert result is True
    assert len(captured_g_attrs) == 1
    assert captured_g_attrs[0]["tenant_id"] is None


@pytest.mark.asyncio
async def test_extensions_cleaned_up_after_processing(test_domain):
    """Extensions are not leaked into the outer domain context after processing."""
    message = _make_message_with_extensions(
        {"tenant_id": "acme-corp", "custom_key": "custom_value"}
    )

    engine = Engine(domain=test_domain, test_mode=True)

    with test_domain.domain_context():
        await engine.handle_message(ExtensionCapturingHandler, message)
        # After handle_message returns, the inner domain context is popped
        assert g.get("tenant_id") is None
        assert g.get("custom_key") is None
        assert g.get("message_in_context") is None


@pytest.mark.asyncio
async def test_extensions_cleaned_up_on_error(test_domain):
    """Extensions are cleaned up even when handler raises an exception."""

    class FailingHandler(BaseEventHandler):
        @handle(UserRegistered)
        def on_registered(self, event: UserRegistered) -> None:
            # Capture before failing
            captured_g_attrs.append({"tenant_id": g.get("tenant_id")})
            raise RuntimeError("intentional failure")

    test_domain.register(FailingHandler, part_of=User)
    test_domain.init(traverse=False)

    message = _make_message_with_extensions({"tenant_id": "acme-corp"})

    engine = Engine(domain=test_domain, test_mode=True)

    with test_domain.domain_context():
        result = await engine.handle_message(FailingHandler, message)

        assert result is False
        # Was available during execution
        assert captured_g_attrs[0]["tenant_id"] == "acme-corp"
        # Cleaned up after
        assert g.get("tenant_id") is None
