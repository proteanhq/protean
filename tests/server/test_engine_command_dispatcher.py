"""Tests for CommandDispatcher (engine.py lines 27-116).

Covers initialization, domain object caching, handler resolution,
message dispatch, and error delegation using pure mocks (no infrastructure).
"""

from unittest.mock import MagicMock, Mock, patch

from protean.server.engine import CommandDispatcher
from protean.utils.eventing import Message


def _make_mock_handler(type_string: str = "Test.SomeCommand.v1") -> MagicMock:
    """Create a mock command handler class with a __type__ mapping."""
    handler_cls = MagicMock()
    handler_cls.meta_ = MagicMock()
    handler_cls.__name__ = "MockCommandHandler"
    return handler_cls


def _make_mock_item(type_string: str = "Test.SomeCommand.v1") -> Mock:
    """Create a mock domain object whose class has __type__."""
    item_cls = type("MockCommand", (), {"__type__": type_string})
    return item_cls()


def _make_dispatcher(
    handler_map: dict | None = None,
    stream_category: str = "test::command",
) -> CommandDispatcher:
    """Build a CommandDispatcher with sensible defaults."""
    source_handler_cls = MagicMock()
    source_handler_cls.meta_ = MagicMock()
    if handler_map is None:
        handler_map = {}
    return CommandDispatcher(stream_category, handler_map, source_handler_cls)


# ---------------------------------------------------------------------------
# 1. __init__ sets all attributes correctly
# ---------------------------------------------------------------------------
class TestCommandDispatcherInit:
    def test_stream_category_stored(self):
        dispatcher = _make_dispatcher(stream_category="orders::command")
        assert dispatcher._stream_category == "orders::command"

    def test_handler_map_stored(self):
        handler = _make_mock_handler()
        handler_map = {"Test.CreateOrder.v1": handler}
        dispatcher = _make_dispatcher(handler_map=handler_map)
        assert dispatcher._handler_map is handler_map

    def test_last_resolved_handler_initialized_to_none(self):
        dispatcher = _make_dispatcher()
        assert dispatcher._last_resolved_handler is None

    def test_last_resolved_item_initialized_to_none(self):
        dispatcher = _make_dispatcher()
        assert dispatcher._last_resolved_item is None

    def test_name_contains_stream_category(self):
        dispatcher = _make_dispatcher(stream_category="payments::command")
        assert dispatcher.__name__ == "Commands:payments::command"

    def test_qualname_matches_name(self):
        dispatcher = _make_dispatcher(stream_category="payments::command")
        assert dispatcher.__qualname__ == dispatcher.__name__

    def test_module_is_engine(self):
        dispatcher = _make_dispatcher()
        assert dispatcher.__module__ == "protean.server.engine"

    def test_meta_copied_from_source_handler(self):
        source_handler_cls = MagicMock()
        source_meta = MagicMock()
        source_handler_cls.meta_ = source_meta
        dispatcher = CommandDispatcher("stream", {}, source_handler_cls)
        assert dispatcher.meta_ is source_meta


# ---------------------------------------------------------------------------
# 2-4. _to_domain_object: cache behaviour and fallback
# ---------------------------------------------------------------------------
class TestToDomainObject:
    def test_returns_cached_item_and_clears_cache(self):
        """When _last_resolved_item is set, return it and clear the slot."""
        dispatcher = _make_dispatcher()
        sentinel = object()
        dispatcher._last_resolved_item = sentinel

        result = dispatcher._to_domain_object(MagicMock())
        assert result is sentinel
        assert dispatcher._last_resolved_item is None

    def test_calls_to_domain_object_for_message_instance(self):
        """For a Message, delegate to message.to_domain_object()."""
        dispatcher = _make_dispatcher()
        mock_message = MagicMock(spec=Message)
        expected = _make_mock_item()
        mock_message.to_domain_object.return_value = expected

        result = dispatcher._to_domain_object(mock_message)
        assert result is expected
        mock_message.to_domain_object.assert_called_once()

    def test_returns_message_directly_when_not_message_instance(self):
        """For a non-Message object, return it as-is."""
        dispatcher = _make_dispatcher()
        plain_item = _make_mock_item()

        result = dispatcher._to_domain_object(plain_item)
        assert result is plain_item


# ---------------------------------------------------------------------------
# 5-8. resolve_handler
# ---------------------------------------------------------------------------
class TestResolveHandler:
    def test_returns_none_when_deserialization_yields_none(self):
        """resolve_handler returns None when to_domain_object returns None."""
        dispatcher = _make_dispatcher()
        mock_message = MagicMock(spec=Message)
        mock_message.to_domain_object.return_value = None

        assert dispatcher.resolve_handler(mock_message) is None

    def test_caches_resolved_item(self):
        """After resolve_handler, _last_resolved_item holds the domain object."""
        handler = _make_mock_handler()
        dispatcher = _make_dispatcher(handler_map={"Test.MyCmd.v1": handler})
        item = _make_mock_item("Test.MyCmd.v1")

        mock_message = MagicMock(spec=Message)
        mock_message.to_domain_object.return_value = item

        dispatcher.resolve_handler(mock_message)
        assert dispatcher._last_resolved_item is item

    def test_returns_correct_handler_from_map(self):
        """resolve_handler returns the handler class mapped to the command type."""
        handler = _make_mock_handler()
        dispatcher = _make_dispatcher(handler_map={"Test.PlaceOrder.v1": handler})
        item = _make_mock_item("Test.PlaceOrder.v1")

        mock_message = MagicMock(spec=Message)
        mock_message.to_domain_object.return_value = item

        result = dispatcher.resolve_handler(mock_message)
        assert result is handler

    def test_returns_none_for_unknown_command_type(self):
        """resolve_handler returns None when no handler is registered for the type."""
        dispatcher = _make_dispatcher(handler_map={})
        item = _make_mock_item("Test.UnknownCommand.v1")

        mock_message = MagicMock(spec=Message)
        mock_message.to_domain_object.return_value = item

        result = dispatcher.resolve_handler(mock_message)
        assert result is None

    def test_returns_handler_for_non_message_input(self):
        """resolve_handler works when passed a raw domain object instead of a Message."""
        handler = _make_mock_handler()
        dispatcher = _make_dispatcher(handler_map={"Test.DirectCmd.v1": handler})
        item = _make_mock_item("Test.DirectCmd.v1")

        result = dispatcher.resolve_handler(item)
        assert result is handler


# ---------------------------------------------------------------------------
# 9-11. _handle
# ---------------------------------------------------------------------------
class TestHandle:
    def test_returns_none_when_item_is_none(self):
        """_handle returns None when _to_domain_object yields None."""
        dispatcher = _make_dispatcher()
        with patch.object(dispatcher, "_to_domain_object", return_value=None):
            assert dispatcher._handle(MagicMock()) is None

    def test_returns_none_when_no_handler_registered(self):
        """_handle returns None and logs warning when handler_map has no match."""
        dispatcher = _make_dispatcher(handler_map={})
        item = _make_mock_item("Test.Unregistered.v1")
        with patch.object(dispatcher, "_to_domain_object", return_value=item):
            result = dispatcher._handle(MagicMock())
        assert result is None

    def test_sets_last_resolved_handler(self):
        """_handle stores the resolved handler class in _last_resolved_handler."""
        handler = _make_mock_handler()
        handler._handle.return_value = "ok"
        dispatcher = _make_dispatcher(handler_map={"Test.Cmd.v1": handler})
        item = _make_mock_item("Test.Cmd.v1")
        with patch.object(dispatcher, "_to_domain_object", return_value=item):
            dispatcher._handle(MagicMock())
        assert dispatcher._last_resolved_handler is handler

    def test_sets_last_resolved_handler_to_none_when_unmatched(self):
        """_handle sets _last_resolved_handler to None when no handler matches."""
        dispatcher = _make_dispatcher(handler_map={})
        item = _make_mock_item("Test.Unknown.v1")
        with patch.object(dispatcher, "_to_domain_object", return_value=item):
            dispatcher._handle(MagicMock())
        assert dispatcher._last_resolved_handler is None

    def test_delegates_to_handler_cls_handle(self):
        """_handle calls handler_cls._handle(item) and returns its result."""
        handler = _make_mock_handler()
        handler._handle.return_value = "handled-result"
        dispatcher = _make_dispatcher(handler_map={"Test.DoStuff.v1": handler})
        item = _make_mock_item("Test.DoStuff.v1")
        with patch.object(dispatcher, "_to_domain_object", return_value=item):
            result = dispatcher._handle(MagicMock())
        assert result == "handled-result"
        handler._handle.assert_called_once_with(item)

    def test_handle_uses_cached_item_from_resolve_handler(self):
        """When resolve_handler was called first, _handle reuses the cached item."""
        handler = _make_mock_handler()
        handler._handle.return_value = "success"
        dispatcher = _make_dispatcher(handler_map={"Test.Cmd.v1": handler})
        item = _make_mock_item("Test.Cmd.v1")

        # Simulate resolve_handler being called first (as in the subscription flow)
        mock_message = MagicMock(spec=Message)
        mock_message.to_domain_object.return_value = item
        dispatcher.resolve_handler(mock_message)

        # Now _handle should use the cached item, not call to_domain_object again
        result = dispatcher._handle(mock_message)
        assert result == "success"
        handler._handle.assert_called_once_with(item)
        # to_domain_object was called once (in resolve_handler), not twice
        assert mock_message.to_domain_object.call_count == 1


# ---------------------------------------------------------------------------
# 12-13. handle_error
# ---------------------------------------------------------------------------
class TestHandleError:
    def test_delegates_to_resolved_handler(self):
        """handle_error calls handler_cls.handle_error when a handler was resolved."""
        handler = _make_mock_handler()
        dispatcher = _make_dispatcher()
        dispatcher._last_resolved_handler = handler

        exc = RuntimeError("boom")
        message = MagicMock()
        dispatcher.handle_error(exc, message)

        handler.handle_error.assert_called_once_with(exc, message)

    def test_does_nothing_when_no_handler_resolved(self):
        """handle_error is a no-op when _last_resolved_handler is None."""
        dispatcher = _make_dispatcher()
        dispatcher._last_resolved_handler = None

        # Should not raise
        dispatcher.handle_error(RuntimeError("boom"), MagicMock())

    def test_does_nothing_when_handler_has_no_handle_error(self):
        """handle_error skips delegation when handler lacks handle_error method."""
        handler = Mock(spec=[])  # spec=[] means no attributes
        dispatcher = _make_dispatcher()
        dispatcher._last_resolved_handler = handler

        # Should not raise
        dispatcher.handle_error(RuntimeError("boom"), MagicMock())
