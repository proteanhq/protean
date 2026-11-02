"""Tests for Bucket H: Type Safety (Engine).

Finding #22: CommandDispatcher has complete type hints.
Finding #23: CommandDispatcher handles None from deserialization gracefully.
"""

import logging
from typing import get_type_hints
from unittest.mock import MagicMock

import pytest

from protean.server.engine import CommandDispatcher
from protean.utils.eventing import Message


# ---------------------------------------------------------------------------
# Finding #22: CommandDispatcher type hints
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "method, annotated",
    [
        (
            "__init__",
            {"stream_category", "handler_map", "source_handler_cls", "return"},
        ),
        ("_to_domain_object", {"return"}),
        ("resolve_handler", {"message", "return"}),
        ("_handle", {"message", "return"}),
        ("handle_error", {"return"}),
    ],
)
def test_command_dispatcher_methods_are_annotated(method, annotated):
    hints = get_type_hints(getattr(CommandDispatcher, method))
    assert annotated <= set(hints)
    if method == "__init__":
        assert hints["return"] is type(None)


# ---------------------------------------------------------------------------
# Finding #23: Null checks on deserialized messages
# ---------------------------------------------------------------------------
class TestCommandDispatcherNullSafety:
    """A real Message never deserializes to None, so these tests stand in a
    Message whose ``to_domain_object`` returns None."""

    def _make_dispatcher(self):
        class SourceHandler:
            meta_ = None

        return CommandDispatcher("test::stream", {}, SourceHandler)

    def _message_that_deserializes_to_none(self):
        message = MagicMock(spec=Message)
        message.to_domain_object.return_value = None
        return message

    @pytest.mark.parametrize("method", ["resolve_handler", "_handle"])
    def test_returns_none_and_warns_on_deserialization_failure(self, method, caplog):
        """Neither method raises AttributeError when deserialization returns None."""
        dispatcher = self._make_dispatcher()

        with caplog.at_level(logging.WARNING):
            result = getattr(dispatcher, method)(
                self._message_that_deserializes_to_none()
            )

        assert result is None
        assert "Failed to deserialize message in stream 'test::stream'" in caplog.text
