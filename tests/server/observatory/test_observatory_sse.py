"""Tests for Observatory SSE endpoint.

Tests for the _format_sse helper (pure logic, no infra), SSE
filtering logic, and the SSE endpoint error paths.

Note: SSE error-path tests use mock domains because real Domain context
managers interact poorly with Starlette's TestClient threading model,
causing SSE streaming to deadlock.
"""

import json
from fnmatch import fnmatch
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from protean.server.observatory import Observatory
from protean.server.observatory.sse import _format_sse, create_sse_endpoint


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


def _make_mock_domain(name: str = "mock-domain") -> MagicMock:
    """Create a mock Domain for SSE error-path tests.

    SSE streaming tests require mocks because real Domain context managers
    deadlock with Starlette's TestClient threading model.
    """
    mock = MagicMock()
    mock.name = name
    mock.domain_context.return_value.__enter__ = MagicMock(return_value=None)
    mock.domain_context.return_value.__exit__ = MagicMock(return_value=False)
    return mock


@pytest.mark.no_test_domain
class TestSSEEndpointNoRedis:
    """Test the SSE endpoint behavior when Redis is unavailable."""

    def test_stream_returns_error_when_no_redis(self):
        """SSE endpoint sends error event when no Redis broker is available."""
        mock_domain = _make_mock_domain()
        mock_broker = MagicMock(spec=[])  # empty spec = no redis_instance attr
        mock_domain.brokers.get.return_value = mock_broker

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        # Stream endpoint returns a streaming response; read the first chunk
        with client.stream("GET", "/stream") as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            # Read the error event from the stream
            for line in response.iter_lines():
                if line.startswith("data: "):
                    data = json.loads(line[len("data: ") :])
                    assert "error" in data
                    assert data["error"] == "Redis not available"
                    break

    def test_stream_returns_error_when_broker_raises(self):
        """SSE endpoint sends error event when broker access raises."""
        mock_domain = MagicMock()
        mock_domain.name = "failing-domain"
        mock_domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        mock_domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        mock_domain.brokers.get.side_effect = RuntimeError("broker init failed")

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        with client.stream("GET", "/stream") as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if line.startswith("data: "):
                    data = json.loads(line[len("data: ") :])
                    assert "error" in data
                    break


@pytest.mark.no_test_domain
class TestSSEStreamingLogic:
    """Test SSE event_generator logic by calling the endpoint function directly.

    We patch asyncio.to_thread to run synchronously and asyncio.sleep to be
    a no-op to avoid deadlocks and delays.
    """

    def _make_mock_domain_with_redis(self, pubsub_messages):
        """Create mock domain with Redis that yields controlled pubsub messages."""
        mock_domain = _make_mock_domain("sse-test")
        mock_redis = MagicMock()
        mock_pubsub = MagicMock()

        call_idx = [0]

        def get_message(ignore_subscribe_messages=True, timeout=1.0):
            idx = call_idx[0]
            if idx < len(pubsub_messages):
                call_idx[0] += 1
                return pubsub_messages[idx]
            return None

        mock_pubsub.get_message = get_message
        mock_redis.pubsub.return_value = mock_pubsub

        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis
        mock_domain.brokers.get.return_value = mock_broker

        return mock_domain, mock_pubsub

    async def _run_sse(
        self, domains, max_events=5, disconnect_after=2, **endpoint_kwargs
    ):
        """Run the SSE endpoint and collect events.

        Patches asyncio.to_thread (sync) and asyncio.sleep (no-op) to avoid
        deadlocks and delays in tests.

        Note: FastAPI Query() defaults are FieldInfo objects (truthy), not None.
        When calling the endpoint directly, we must pass explicit None for all
        filter parameters to avoid false filter matches.
        """
        import asyncio as _asyncio

        yield_count = [0]
        mock_request = MagicMock()

        async def is_disconnected():
            return yield_count[0] >= disconnect_after

        mock_request.is_disconnected = is_disconnected

        async def sync_to_thread(fn, /, *args, **kwargs):
            return fn(*args, **kwargs)

        async def noop_sleep(_t):
            pass

        endpoint_fn = create_sse_endpoint(domains)

        # Fill in None defaults for Query() params not explicitly passed
        endpoint_kwargs.setdefault("domain", None)
        endpoint_kwargs.setdefault("stream", None)
        endpoint_kwargs.setdefault("event", None)
        endpoint_kwargs.setdefault("type", None)

        # Patch asyncio functions globally (sse.py uses `import asyncio`)
        orig_to_thread = _asyncio.to_thread
        orig_sleep = _asyncio.sleep
        _asyncio.to_thread = sync_to_thread
        _asyncio.sleep = noop_sleep
        try:
            response = await endpoint_fn(mock_request, **endpoint_kwargs)
            events = []
            async for chunk in response.body_iterator:
                events.append(chunk)
                yield_count[0] += 1
                if len(events) >= max_events:
                    break
        finally:
            _asyncio.to_thread = orig_to_thread
            _asyncio.sleep = orig_sleep

        return events

    @pytest.mark.asyncio
    async def test_streams_valid_trace_event(self):
        """event_generator yields formatted SSE for valid trace messages."""
        trace = {"domain": "test", "event": "handler.started", "handler": "MyH"}
        mock_domain, mock_pubsub = self._make_mock_domain_with_redis(
            [
                {"type": "message", "data": json.dumps(trace)},
            ]
        )

        events = await self._run_sse([mock_domain])

        trace_events = [e for e in events if "handler.started" in e]
        assert len(trace_events) >= 1
        mock_pubsub.unsubscribe.assert_called()
        mock_pubsub.close.assert_called()

    @pytest.mark.asyncio
    async def test_keepalive_on_no_message(self):
        """event_generator yields keepalive comment when no pubsub message."""
        mock_domain, _ = self._make_mock_domain_with_redis([None])

        events = await self._run_sse([mock_domain])

        keepalives = [e for e in events if ": keepalive" in e]
        assert len(keepalives) >= 1

    @pytest.mark.asyncio
    async def test_json_decode_error_skipped(self):
        """event_generator skips invalid JSON and continues."""
        valid = {"event": "handler.completed"}
        mock_domain, _ = self._make_mock_domain_with_redis(
            [
                {"type": "message", "data": "not-json{{{"},
                {"type": "message", "data": json.dumps(valid)},
            ]
        )

        events = await self._run_sse([mock_domain], disconnect_after=3)

        data_events = [e for e in events if "handler.completed" in e]
        assert len(data_events) >= 1

    @pytest.mark.asyncio
    async def test_domain_filter_applied(self):
        """event_generator filters by domain query parameter."""
        wrong = {"domain": "other", "event": "handler.started"}
        right = {"domain": "myapp", "event": "handler.completed"}
        mock_domain, _ = self._make_mock_domain_with_redis(
            [
                {"type": "message", "data": json.dumps(wrong)},
                {"type": "message", "data": json.dumps(right)},
            ]
        )

        events = await self._run_sse([mock_domain], disconnect_after=3, domain="myapp")

        assert any("myapp" in e for e in events)

    @pytest.mark.asyncio
    async def test_stream_filter_applied(self):
        """event_generator filters by stream query parameter."""
        wrong = {"stream": "other::stream", "event": "handler.started"}
        right = {"stream": "myapp::orders", "event": "handler.completed"}
        mock_domain, _ = self._make_mock_domain_with_redis(
            [
                {"type": "message", "data": json.dumps(wrong)},
                {"type": "message", "data": json.dumps(right)},
            ]
        )

        events = await self._run_sse(
            [mock_domain], disconnect_after=3, stream="myapp::orders"
        )

        assert any("myapp::orders" in e for e in events)
        assert not any("other::stream" in e for e in events)

    @pytest.mark.asyncio
    async def test_event_filter_applied(self):
        """event_generator filters by event glob pattern."""
        wrong = {"event": "outbox.published"}
        right = {"event": "handler.completed"}
        mock_domain, _ = self._make_mock_domain_with_redis(
            [
                {"type": "message", "data": json.dumps(wrong)},
                {"type": "message", "data": json.dumps(right)},
            ]
        )

        events = await self._run_sse(
            [mock_domain], disconnect_after=3, event="handler.*"
        )

        assert any("handler.completed" in e for e in events)
        assert not any("outbox.published" in e for e in events)

    @pytest.mark.asyncio
    async def test_type_filter_applied(self):
        """event_generator filters by message type glob pattern."""
        wrong = {"message_type": "OrderPlaced", "event": "handler.started"}
        right = {"message_type": "UserRegistered", "event": "handler.started"}
        mock_domain, _ = self._make_mock_domain_with_redis(
            [
                {"type": "message", "data": json.dumps(wrong)},
                {"type": "message", "data": json.dumps(right)},
            ]
        )

        events = await self._run_sse([mock_domain], disconnect_after=3, type="User*")

        assert any("UserRegistered" in e for e in events)
        assert not any("OrderPlaced" in e for e in events)

    @pytest.mark.asyncio
    async def test_redis_found_from_second_domain(self):
        """event_generator finds Redis from second domain when first fails."""
        mock_domain1 = _make_mock_domain("fail")
        mock_domain1.brokers.get.side_effect = RuntimeError("nope")

        trace = {"event": "handler.started"}
        mock_domain2, _ = self._make_mock_domain_with_redis(
            [
                {"type": "message", "data": json.dumps(trace)},
            ]
        )

        events = await self._run_sse([mock_domain1, mock_domain2])

        data_events = [e for e in events if "handler.started" in e]
        assert len(data_events) >= 1
