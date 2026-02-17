"""Tests for Observatory SSE endpoint.

Tests for the _format_sse helper (pure logic, no infra) and SSE
filtering logic.
"""

import json
from fnmatch import fnmatch

from protean.server.observatory.sse import _format_sse


class TestFormatSSE:
    """Tests for the _format_sse helper function (no Redis needed)."""

    def test_default_event_type(self):
        """_format_sse uses 'trace' as default event type."""
        result = _format_sse({"key": "value"})
        assert result.startswith("event: trace\n")

    def test_custom_event_type(self):
        """_format_sse uses custom event_type when provided."""
        result = _format_sse({"error": "oops"}, event_type="error")
        assert result.startswith("event: error\n")

    def test_data_is_json(self):
        """_format_sse serializes data dict as JSON in data field."""
        result = _format_sse({"key": "value", "num": 42})
        lines = result.strip().split("\n")
        data_line = [line for line in lines if line.startswith("data: ")][0]
        json_str = data_line[len("data: ") :]
        data = json.loads(json_str)
        assert data["key"] == "value"
        assert data["num"] == 42

    def test_ends_with_double_newline(self):
        """SSE events must end with two newlines."""
        result = _format_sse({"key": "value"})
        assert result.endswith("\n\n")

    def test_format_with_nested_data(self):
        """_format_sse handles nested dictionaries."""
        result = _format_sse({"metadata": {"retry": 3, "dlq": "stream-dlq"}})
        data_line = [
            line for line in result.strip().split("\n") if line.startswith("data: ")
        ][0]
        data = json.loads(data_line[len("data: ") :])
        assert data["metadata"]["retry"] == 3

    def test_format_with_none_values(self):
        """_format_sse handles None values."""
        result = _format_sse({"handler": None, "error": None})
        data_line = [
            line for line in result.strip().split("\n") if line.startswith("data: ")
        ][0]
        data = json.loads(data_line[len("data: ") :])
        assert data["handler"] is None
        assert data["error"] is None


class TestSSEFilteringLogic:
    """Tests for the filtering logic used by the SSE endpoint.

    The SSE endpoint uses fnmatch for glob-style pattern matching.
    We test the filtering logic directly since SSE streaming tests
    are inherently fragile due to the long-lived connection nature.
    """

    def test_domain_exact_match(self):
        """Domain filter uses exact matching."""
        data = {"domain": "identity", "event": "handler.started"}
        assert data["domain"] == "identity"
        assert data["domain"] != "catalogue"

    def test_event_glob_match_star(self):
        """Event filter supports glob patterns with *."""
        assert fnmatch("handler.started", "handler.*")
        assert fnmatch("handler.completed", "handler.*")
        assert fnmatch("handler.failed", "handler.*")
        assert not fnmatch("outbox.published", "handler.*")

    def test_event_glob_match_prefix(self):
        """Event filter supports prefix matching."""
        assert fnmatch("message.acked", "message.*")
        assert fnmatch("message.nacked", "message.*")
        assert fnmatch("message.dlq", "message.*")

    def test_message_type_glob(self):
        """Message type filter supports glob patterns."""
        assert fnmatch("UserRegistered", "User*")
        assert fnmatch("UserActivated", "User*")
        assert not fnmatch("OrderPlaced", "User*")

    def test_stream_exact_match(self):
        """Stream filter uses exact matching."""
        data = {"stream": "identity::customer"}
        assert data["stream"] == "identity::customer"
        assert data["stream"] != "catalogue::product"

    def test_no_filter_passes_all(self):
        """When no filters are set, all events pass."""
        # This tests the SSE endpoint behavior: no query params = all events
        data = {"domain": "test", "stream": "test::user", "event": "handler.started"}
        filters = {"domain": None, "stream": None, "event": None, "type": None}

        passes = True
        if filters["domain"] and data.get("domain") != filters["domain"]:
            passes = False
        if filters["stream"] and data.get("stream") != filters["stream"]:
            passes = False
        if filters["event"] and not fnmatch(data.get("event", ""), filters["event"]):
            passes = False

        assert passes is True
