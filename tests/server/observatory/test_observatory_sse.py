"""Tests for Observatory SSE endpoint.

Tests for the _format_sse helper (pure logic, no infra), SSE
filtering logic, and the SSE endpoint itself.

The endpoint tests use real domains. The core test lane has no Redis
server, so the streaming tests replace only the raw Redis client on the
real broker (``broker.redis_instance``) with a fake that yields
controlled pub/sub messages.
"""

import json
from fnmatch import fnmatch
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from protean import Domain
from protean.server.observatory import Observatory
from protean.server.observatory.sse import _format_sse, create_sse_endpoint


class TestFormatSSE:
    """Tests for the _format_sse helper function (no Redis needed)."""

    @pytest.mark.parametrize(
        "kwargs, first_line",
        [({}, "event: trace\n"), ({"event_type": "error"}, "event: error\n")],
        ids=["default-trace", "custom"],
    )
    def test_event_type(self, kwargs, first_line):
        """_format_sse uses 'trace' unless an event_type is given."""
        assert _format_sse({"key": "value"}, **kwargs).startswith(first_line)

    @pytest.mark.parametrize(
        "payload",
        [
            {"key": "value", "num": 42},
            {"metadata": {"retry": 3, "dlq": "stream-dlq"}},
            {"handler": None, "error": None},
        ],
        ids=["flat", "nested", "none-values"],
    )
    def test_data_line_is_the_payload_as_json(self, payload):
        result = _format_sse(payload)
        data_line = next(
            line for line in result.strip().split("\n") if line.startswith("data: ")
        )
        assert json.loads(data_line[len("data: ") :]) == payload

    def test_ends_with_double_newline(self):
        """SSE events must end with two newlines."""
        result = _format_sse({"key": "value"})
        assert result.endswith("\n\n")


class TestSSEFilteringLogic:
    """Tests for the matching rules the SSE endpoint's filters use.

    The endpoint matches ``event`` and ``type`` with fnmatch glob patterns
    and ``domain`` and ``stream`` exactly. These tests pin those rules on
    plain values; ``TestSSEStreamingLogic`` calls the endpoint function from
    ``create_sse_endpoint`` with each filter.
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


def _domain_without_redis(name: str = "no-redis") -> Domain:
    """A real domain on the inline broker, which has no Redis client."""
    domain = Domain(name=name, config={"brokers": {"default": {"provider": "inline"}}})
    domain.init(traverse=False)
    return domain


def _broken_domain(monkeypatch, name: str = "broken") -> Domain:
    """A real domain whose broker lookup raises, as when a broker fails to start."""
    domain = _domain_without_redis(name)

    def _raise(*args, **kwargs):
        raise RuntimeError("broker init failed")

    monkeypatch.setattr(domain.brokers, "get", _raise)
    return domain


def _fake_redis(pubsub_messages: list) -> tuple[MagicMock, MagicMock]:
    """A fake Redis client whose pub/sub yields the given messages, then None."""
    fake_redis = MagicMock()
    pubsub = MagicMock()
    remaining = list(pubsub_messages)

    def get_message(ignore_subscribe_messages=True, timeout=1.0):
        return remaining.pop(0) if remaining else None

    pubsub.get_message = get_message
    fake_redis.pubsub.return_value = pubsub
    return fake_redis, pubsub


@pytest.mark.no_test_domain
class TestSSEEndpointNoRedis:
    """Test the SSE endpoint behavior when Redis is unavailable."""

    def _first_data(self, domains: list[Domain]) -> dict:
        client = TestClient(Observatory(domains=domains).app)
        with client.stream("GET", "/stream") as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            for line in response.iter_lines():
                if line.startswith("data: "):
                    return json.loads(line[len("data: ") :])
        raise AssertionError("the stream sent no data event")

    def test_stream_returns_error_when_no_redis(self):
        """SSE endpoint sends error event when no Redis broker is available."""
        data = self._first_data([_domain_without_redis()])
        assert data == {"error": "Redis not available"}

    def test_stream_returns_error_when_broker_raises(self, monkeypatch):
        """SSE endpoint sends error event when broker access raises."""
        data = self._first_data([_broken_domain(monkeypatch)])
        assert data == {"error": "Redis not available"}


class TestSSEStreamingLogic:
    """Test SSE event_generator logic by calling the endpoint function directly."""

    @pytest.fixture
    def redis_domain(self, test_domain, monkeypatch):
        """The real test domain, with a fake Redis client under its broker."""

        def _attach(pubsub_messages: list) -> tuple[Domain, MagicMock]:
            fake_redis, pubsub = _fake_redis(pubsub_messages)
            broker = test_domain.brokers.get("default")
            monkeypatch.setattr(broker, "redis_instance", fake_redis)
            return test_domain, pubsub

        return _attach

    async def _run_sse(
        self, domains, max_events=5, disconnect_after=2, **endpoint_kwargs
    ):
        """Run the SSE endpoint and collect events.

        The client counts as disconnected after ``disconnect_after`` chunks.

        Note: FastAPI Query() defaults are FieldInfo objects (truthy), not None.
        When calling the endpoint directly, we must pass explicit None for all
        filter parameters to avoid false filter matches.
        """
        yield_count = [0]

        class _Request:
            async def is_disconnected(self):
                return yield_count[0] >= disconnect_after

        endpoint_fn = create_sse_endpoint(domains)

        # Fill in None defaults for Query() params not explicitly passed
        endpoint_kwargs.setdefault("domain", None)
        endpoint_kwargs.setdefault("stream", None)
        endpoint_kwargs.setdefault("event", None)
        endpoint_kwargs.setdefault("type", None)

        response = await endpoint_fn(_Request(), **endpoint_kwargs)
        events = []
        async for chunk in response.body_iterator:
            events.append(chunk)
            yield_count[0] += 1
            if len(events) >= max_events:
                break
        await response.body_iterator.aclose()
        return events

    @pytest.mark.asyncio
    async def test_streams_valid_trace_event(self, redis_domain):
        """event_generator yields formatted SSE for valid trace messages."""
        trace = {"domain": "test", "event": "handler.started", "handler": "MyH"}
        domain, pubsub = redis_domain(
            [
                {"type": "message", "data": json.dumps(trace)},
            ]
        )

        events = await self._run_sse([domain])

        trace_events = [e for e in events if "handler.started" in e]
        assert len(trace_events) >= 1
        pubsub.unsubscribe.assert_called()
        pubsub.close.assert_called()

    @pytest.mark.asyncio
    async def test_keepalive_on_no_message(self, redis_domain):
        """event_generator yields keepalive comment when no pubsub message."""
        domain, _ = redis_domain([None])

        events = await self._run_sse([domain])

        keepalives = [e for e in events if ": keepalive" in e]
        assert len(keepalives) >= 1

    @pytest.mark.asyncio
    async def test_json_decode_error_skipped(self, redis_domain):
        """event_generator skips invalid JSON and continues."""
        valid = {"event": "handler.completed"}
        domain, _ = redis_domain(
            [
                {"type": "message", "data": "not-json{{{"},
                {"type": "message", "data": json.dumps(valid)},
            ]
        )

        events = await self._run_sse([domain], disconnect_after=3)

        data_events = [e for e in events if "handler.completed" in e]
        assert len(data_events) >= 1

    @pytest.mark.asyncio
    async def test_domain_filter_applied(self, redis_domain):
        """event_generator filters by domain query parameter."""
        wrong = {"domain": "other", "event": "handler.started"}
        right = {"domain": "myapp", "event": "handler.completed"}
        domain, _ = redis_domain(
            [
                {"type": "message", "data": json.dumps(wrong)},
                {"type": "message", "data": json.dumps(right)},
            ]
        )

        events = await self._run_sse([domain], disconnect_after=3, domain="myapp")

        assert any("myapp" in e for e in events)
        assert not any('"other"' in e for e in events)

    @pytest.mark.asyncio
    async def test_stream_filter_applied(self, redis_domain):
        """event_generator filters by stream query parameter."""
        wrong = {"stream": "other::stream", "event": "handler.started"}
        right = {"stream": "myapp::orders", "event": "handler.completed"}
        domain, _ = redis_domain(
            [
                {"type": "message", "data": json.dumps(wrong)},
                {"type": "message", "data": json.dumps(right)},
            ]
        )

        events = await self._run_sse(
            [domain], disconnect_after=3, stream="myapp::orders"
        )

        assert any("myapp::orders" in e for e in events)
        assert not any("other::stream" in e for e in events)

    @pytest.mark.asyncio
    async def test_event_filter_applied(self, redis_domain):
        """event_generator filters by event glob pattern."""
        wrong = {"event": "outbox.published"}
        right = {"event": "handler.completed"}
        domain, _ = redis_domain(
            [
                {"type": "message", "data": json.dumps(wrong)},
                {"type": "message", "data": json.dumps(right)},
            ]
        )

        events = await self._run_sse([domain], disconnect_after=3, event="handler.*")

        assert any("handler.completed" in e for e in events)
        assert not any("outbox.published" in e for e in events)

    @pytest.mark.asyncio
    async def test_type_filter_applied(self, redis_domain):
        """event_generator filters by message type glob pattern."""
        wrong = {"message_type": "OrderPlaced", "event": "handler.started"}
        right = {"message_type": "UserRegistered", "event": "handler.started"}
        domain, _ = redis_domain(
            [
                {"type": "message", "data": json.dumps(wrong)},
                {"type": "message", "data": json.dumps(right)},
            ]
        )

        events = await self._run_sse([domain], disconnect_after=3, type="User*")

        assert any("UserRegistered" in e for e in events)
        assert not any("OrderPlaced" in e for e in events)

    @pytest.mark.asyncio
    async def test_redis_found_from_second_domain(self, redis_domain, monkeypatch):
        """event_generator finds Redis from second domain when first fails."""
        trace = {"event": "handler.started"}
        domain, _ = redis_domain(
            [
                {"type": "message", "data": json.dumps(trace)},
            ]
        )

        events = await self._run_sse([_broken_domain(monkeypatch), domain])

        data_events = [e for e in events if "handler.started" in e]
        assert len(data_events) >= 1
