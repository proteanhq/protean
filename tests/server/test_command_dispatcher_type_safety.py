"""Tests for Bucket H: Type Safety (Engine).

Finding #22: CommandDispatcher has complete type hints.
Finding #23: CommandDispatcher handles None from deserialization gracefully.
"""

from typing import get_type_hints
from unittest.mock import MagicMock, patch

from protean.server.engine import CommandDispatcher
from protean.utils.eventing import Message


# ---------------------------------------------------------------------------
# Finding #22: CommandDispatcher type hints
# ---------------------------------------------------------------------------
class TestCommandDispatcherTypeHints:
    def test_init_has_type_hints(self):
        """__init__ parameters have type annotations."""
        hints = get_type_hints(CommandDispatcher.__init__)
        assert "stream_category" in hints
        assert "handler_map" in hints
        assert "source_handler_cls" in hints
        assert hints["return"] is type(None)

    def test_to_domain_object_has_return_type(self):
        """_to_domain_object has a return type annotation."""
        hints = get_type_hints(CommandDispatcher._to_domain_object)
        assert "return" in hints

    def test_resolve_handler_has_return_type(self):
        """resolve_handler has a return type annotation."""
        hints = get_type_hints(CommandDispatcher.resolve_handler)
        assert "return" in hints

    def test_handle_has_return_type(self):
        """_handle has a return type annotation."""
        hints = get_type_hints(CommandDispatcher._handle)
        assert "return" in hints

    def test_handle_error_has_return_type(self):
        """handle_error has a return type annotation."""
        hints = get_type_hints(CommandDispatcher.handle_error)
        assert "return" in hints

    def test_resolve_handler_has_message_param_type(self):
        """resolve_handler's message parameter has a type annotation."""
        hints = get_type_hints(CommandDispatcher.resolve_handler)
        assert "message" in hints

    def test_handle_has_message_param_type(self):
        """_handle's message parameter has a type annotation."""
        hints = get_type_hints(CommandDispatcher._handle)
        assert "message" in hints


# ---------------------------------------------------------------------------
# Finding #23: Null checks on deserialized messages
# ---------------------------------------------------------------------------
class TestCommandDispatcherNullSafety:
    def _make_dispatcher(self):
        """Create a CommandDispatcher with a mock handler class."""
        mock_handler_cls = MagicMock()
        mock_handler_cls.meta_ = MagicMock()
        handler_map = {"SomeCommand": mock_handler_cls}
        return CommandDispatcher("test::stream", handler_map, mock_handler_cls)

    def test_resolve_handler_returns_none_on_deserialization_failure(self):
        """resolve_handler returns None when to_domain_object returns None."""
        dispatcher = self._make_dispatcher()

        # Use a Message-spec mock so isinstance(message, Message) is bypassed
        # by patching to_domain_object at the dispatcher level
        mock_message = MagicMock(spec=Message)
        mock_message.to_domain_object.return_value = None

        result = dispatcher.resolve_handler(mock_message)
        assert result is None

    def test_handle_returns_none_on_deserialization_failure(self):
        """_handle returns None when _to_domain_object returns None."""
        dispatcher = self._make_dispatcher()

        with patch.object(dispatcher, "_to_domain_object", return_value=None):
            result = dispatcher._handle(MagicMock())
            assert result is None

    def test_handle_does_not_raise_attribute_error_on_none(self):
        """_handle does not raise AttributeError when deserialization returns None."""
        dispatcher = self._make_dispatcher()

        mock_message = MagicMock(spec=Message)
        mock_message.to_domain_object.return_value = None

        # This should NOT raise AttributeError
        result = dispatcher._handle(mock_message)
        assert result is None

    def test_resolve_handler_does_not_raise_attribute_error_on_none(self):
        """resolve_handler does not raise AttributeError when deserialization returns None."""
        dispatcher = self._make_dispatcher()

        mock_message = MagicMock(spec=Message)
        mock_message.to_domain_object.return_value = None

        # This should NOT raise AttributeError
        result = dispatcher.resolve_handler(mock_message)
        assert result is None

    def test_resolve_handler_works_normally_for_valid_message(self):
        """resolve_handler correctly resolves a handler for a valid command."""
        mock_handler_cls = MagicMock()
        mock_handler_cls.meta_ = MagicMock()
        handler_map = {"Test.SomeCommand.v1": mock_handler_cls}
        dispatcher = CommandDispatcher("test::stream", handler_map, mock_handler_cls)

        # Create a mock domain object with __type__ on its class
        mock_item_class = type("MockCommand", (), {"__type__": "Test.SomeCommand.v1"})
        mock_item = mock_item_class()

        mock_message = MagicMock(spec=Message)
        mock_message.to_domain_object.return_value = mock_item

        result = dispatcher.resolve_handler(mock_message)
        assert result is mock_handler_cls

    def test_handle_works_normally_for_valid_message(self):
        """_handle correctly routes a valid command to its handler."""
        mock_handler_cls = MagicMock()
        mock_handler_cls.meta_ = MagicMock()
        mock_handler_cls._handle.return_value = "handled"
        handler_map = {"Test.SomeCommand.v1": mock_handler_cls}
        dispatcher = CommandDispatcher("test::stream", handler_map, mock_handler_cls)

        mock_item_class = type("MockCommand", (), {"__type__": "Test.SomeCommand.v1"})
        mock_item = mock_item_class()

        mock_message = MagicMock(spec=Message)
        mock_message.to_domain_object.return_value = mock_item

        result = dispatcher._handle(mock_message)
        assert result == "handled"
        mock_handler_cls._handle.assert_called_once_with(mock_item)
