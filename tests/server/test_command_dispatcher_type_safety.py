"""Tests for Bucket H: Type Safety (Engine).

Finding #22: CommandDispatcher has complete type hints.
Finding #23: CommandDispatcher handles None from deserialization gracefully.
"""

import logging
from typing import get_type_hints
from unittest.mock import MagicMock

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.fields import Identifier
from protean.server.engine import CommandDispatcher
from protean.utils.eventing import Message
from protean.utils.mixins import handle


class Account(BaseAggregate):
    id: Identifier(identifier=True)


class OpenAccount(BaseCommand):
    account_id: Identifier()


class AccountCommandHandler(BaseCommandHandler):
    @handle(OpenAccount)
    def open(self, command: OpenAccount) -> None:
        pass


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

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Account)
        test_domain.register(OpenAccount, part_of=Account)
        test_domain.register(AccountCommandHandler, part_of=Account)
        test_domain.init(traverse=False)

    def _make_dispatcher(self):
        return CommandDispatcher("test::stream", {}, AccountCommandHandler)

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
