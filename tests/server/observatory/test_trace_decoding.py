"""Observatory trace readers skip malformed entries and nothing else.

Every reader of the trace stream (and the SSE pub/sub feed) decodes each entry
with ``decode_trace``. An entry that does not decode to a JSON object is
skipped. An error raised after decoding is a bug in the reader, so it reaches
the caller instead of being suppressed.
"""

import json
import time
from unittest.mock import MagicMock

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import protean.server.observatory.api as api_module
import protean.server.observatory.routes.handlers as handlers_module
import protean.server.observatory.routes.processes as processes_module
import protean.server.observatory.routes.timeline as timeline_module
import protean.server.observatory.sse as sse_module
from protean.server.observatory import Observatory
from protean.server.observatory.routes.timeline import _load_traces_for_correlation
from protean.server.tracing import decode_trace, decode_trace_payload, trace_number


def _now_id(offset_ms: int = 0) -> bytes:
    return f"{int(time.time() * 1000) - offset_ms}-0".encode()


def _entry(trace: dict, offset_ms: int = 0) -> tuple[bytes, dict]:
    return _now_id(offset_ms), {b"data": json.dumps(trace).encode()}


def _malformed_entries() -> list[tuple[bytes, dict]]:
    return [
        (_now_id(), {b"data": b"{not json"}),
        (_now_id(), {b"data": b"[1, 2]"}),
        (_now_id(), {b"data": b"\xff\xfe"}),
        (_now_id(), {b"other": b"{}"}),
    ]


def _completed(handler: str = "OrderHandler", **extra) -> dict:
    return {
        "event": "handler.completed",
        "handler": handler,
        "duration_ms": 10.0,
        "message_type": "OrderPlaced",
        **extra,
    }


def _failed(handler: str = "OrderHandler", **extra) -> dict:
    return {
        "event": "handler.failed",
        "handler": handler,
        "message_type": "OrderPlaced",
        **extra,
    }


def _raise_type_error(*args, **kwargs):
    # A catch for malformed entries that wraps more than the decoding would
    # swallow a TypeError, so this is the error that tells the two apart.
    raise TypeError("bug after decoding")


def _domain_with_redis(redis_conn: MagicMock) -> MagicMock:
    domain = MagicMock()
    domain.name = "test"
    domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
    domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
    broker = MagicMock()
    broker.redis_instance = redis_conn
    domain.brokers.get.return_value = broker
    return domain


def _client(redis_conn: MagicMock) -> TestClient:
    return TestClient(Observatory(domains=[_domain_with_redis(redis_conn)]).app)


class TestDecodeTracePayload:
    def test_decodes_bytes(self):
        assert decode_trace_payload(b'{"event": "x"}') == {"event": "x"}

    def test_decodes_str(self):
        assert decode_trace_payload('{"event": "x"}') == {"event": "x"}

    @pytest.mark.parametrize(
        "raw",
        [None, b"", "", b"\xff\xfe", "{not json", "[1, 2]", '"text"', "42", 42],
    )
    def test_returns_none_for_a_payload_without_a_json_object(self, raw):
        assert decode_trace_payload(raw) is None

    def test_returns_none_for_an_integer_past_the_digit_limit(self):
        assert decode_trace_payload('{"duration_ms": ' + "1" * 5000 + "}") is None

    def test_returns_none_for_nesting_too_deep_to_decode(self):
        depth = 1_000_000
        assert decode_trace_payload("[" * depth + "]" * depth) is None


class TestDecodeTrace:
    def test_reads_the_bytes_data_key(self):
        assert decode_trace({b"data": b'{"event": "x"}'}) == {"event": "x"}

    def test_reads_the_str_data_key(self):
        assert decode_trace({"data": '{"event": "x"}'}) == {"event": "x"}

    def test_returns_none_without_a_data_key(self):
        assert decode_trace({b"other": b'{"event": "x"}'}) is None

    def test_returns_none_for_bad_json(self):
        assert decode_trace({b"data": b"{not json"}) is None

    def test_returns_none_for_json_that_is_not_an_object(self):
        assert decode_trace({b"data": b"[1, 2]"}) is None


class TestTraceNumber:
    @pytest.mark.parametrize(
        "value, expected", [(3, 3.0), (2.5, 2.5), (0, 0.0), ("12.5", 12.5)]
    )
    def test_returns_a_float_for_a_number(self, value, expected):
        assert trace_number(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            None,
            True,
            "n/a",
            [1],
            {"a": 1},
            float("inf"),
            float("nan"),
            "inf",
            10**400,
        ],
    )
    def test_returns_none_for_anything_else(self, value):
        assert trace_number(value) is None


@pytest.mark.no_test_domain
class TestWorkerThroughput:
    def _redis(self, entries: list) -> MagicMock:
        redis_conn = MagicMock()
        redis_conn.scan.return_value = (0, [b"orders::order"])
        redis_conn.xinfo_groups.return_value = [
            {"name": "Handler", "pending": 0, "lag": 0}
        ]
        redis_conn.xinfo_consumers.return_value = [
            {"name": "Handler-host-1-abc", "pending": 0, "idle": 0}
        ]
        redis_conn.xrange.return_value = entries
        return redis_conn

    def test_malformed_entries_are_skipped(self):
        entries = [
            *_malformed_entries(),
            _entry(_completed(worker_id="Handler-host-1-abc")),
            _entry(_completed(worker_id=["not", "a", "str"])),
        ]

        response = _client(self._redis(entries)).get("/api/workers")

        assert response.status_code == 200
        workers = response.json()["workers"]
        assert len(workers) == 1
        assert workers[0]["throughput"]["total"] == 1

    def test_an_error_after_decoding_reaches_the_caller(self, monkeypatch):
        monkeypatch.setattr(api_module, "_decode_stream_id", _raise_type_error)
        entries = [_entry(_completed(worker_id="Handler-host-1-abc"))]

        with pytest.raises(TypeError, match="bug after decoding"):
            _client(self._redis(entries)).get("/api/workers")

    def test_a_trace_read_failure_shows_zero_throughput(self):
        redis_conn = self._redis([])
        redis_conn.xrange.side_effect = RuntimeError("redis down")

        response = _client(redis_conn).get("/api/workers")

        assert response.status_code == 200
        assert response.json()["workers"][0]["throughput"]["total"] == 0


@pytest.mark.no_test_domain
class TestTraceListing:
    def test_malformed_entries_are_skipped(self):
        redis_conn = MagicMock()
        redis_conn.xrevrange.return_value = [
            *_malformed_entries(),
            _entry(_completed()),
        ]

        response = _client(redis_conn).get("/api/traces")

        assert response.status_code == 200
        traces = response.json()["traces"]
        assert [t["handler"] for t in traces] == ["OrderHandler"]

    def test_an_error_after_decoding_reaches_the_caller(self, monkeypatch):
        monkeypatch.setattr(api_module, "_decode_stream_id", _raise_type_error)
        redis_conn = MagicMock()
        redis_conn.xrevrange.return_value = [_entry(_completed())]

        with pytest.raises(TypeError, match="bug after decoding"):
            _client(redis_conn).get("/api/traces")


@pytest.mark.no_test_domain
class TestTraceOverview:
    def test_malformed_entries_are_skipped(self):
        redis_conn = MagicMock()
        redis_conn.xrange.return_value = [
            *_malformed_entries(),
            _entry(_completed()),
            _entry(_completed(duration_ms="slow")),
            _entry({"event": ["not", "a", "str"]}),
        ]

        response = _client(redis_conn).get("/api/traces/overview?window=15m")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert body["counts"] == {"handler.completed": 2}
        assert body["avg_latency_ms"] == 10.0

    def test_an_error_after_decoding_reaches_the_caller(self, monkeypatch):
        monkeypatch.setattr(api_module, "_decode_stream_id", _raise_type_error)
        redis_conn = MagicMock()
        redis_conn.xrange.return_value = [_entry(_completed())]

        with pytest.raises(TypeError, match="bug after decoding"):
            _client(redis_conn).get("/api/traces/overview?window=1h")


@pytest.mark.no_test_domain
class TestFailedTraces:
    def test_malformed_entries_are_skipped(self):
        redis_conn = MagicMock()
        redis_conn.xrange.return_value = [
            *_malformed_entries(),
            _entry(_failed()),
            _entry({"event": ["not", "a", "str"]}),
        ]

        response = _client(redis_conn).get("/api/traces/failed")

        assert response.status_code == 200
        body = response.json()
        assert body["total_count"] == 1
        assert body["traces"][0]["event"] == "handler.failed"

    def test_an_error_after_decoding_reaches_the_caller(self, monkeypatch):
        monkeypatch.setattr(api_module, "_decode_stream_id", _raise_type_error)
        redis_conn = MagicMock()
        redis_conn.xrange.return_value = [_entry(_failed())]

        with pytest.raises(TypeError, match="bug after decoding"):
            _client(redis_conn).get("/api/traces/failed")


@pytest.mark.no_test_domain
class TestTraceDetail:
    def test_a_malformed_entry_is_reported_as_unparseable(self):
        redis_conn = MagicMock()
        redis_conn.xrange.return_value = [(b"1-0", {b"data": b"[1, 2]"})]

        response = _client(redis_conn).get("/api/traces/1-0")

        assert response.status_code == 500
        assert response.json() == {"error": "Failed to parse trace data"}

    def test_a_trace_is_returned_with_its_stream_id(self):
        redis_conn = MagicMock()
        redis_conn.xrange.return_value = [
            (b"1-0", {b"data": json.dumps(_completed()).encode()})
        ]

        response = _client(redis_conn).get("/api/traces/1-0")

        assert response.status_code == 200
        assert response.json()["_stream_id"] == "1-0"


class TestHandlerTraceMetrics:
    def test_malformed_entries_are_skipped(self):
        redis_conn = MagicMock()
        redis_conn.xrange.return_value = [
            *_malformed_entries(),
            _entry(_completed()),
            _entry(_completed(duration_ms="slow")),
            _entry(_failed()),
            _entry(_completed(handler=["not", "a", "str"])),
            _entry(_completed(event=["not", "a", "str"])),
        ]

        metrics = handlers_module.collect_per_handler_trace_metrics(redis_conn, 300_000)

        assert list(metrics) == ["OrderHandler"]
        assert metrics["OrderHandler"]["processed"] == 2
        assert metrics["OrderHandler"]["failed"] == 1
        assert metrics["OrderHandler"]["avg_latency_ms"] == 10.0

    def test_an_error_after_decoding_reaches_the_caller(self, monkeypatch):
        monkeypatch.setattr(handlers_module, "_decode_stream_id", _raise_type_error)
        redis_conn = MagicMock()
        redis_conn.xrange.return_value = [_entry(_completed())]

        with pytest.raises(TypeError, match="bug after decoding"):
            handlers_module.collect_per_handler_trace_metrics(redis_conn, 300_000)


class TestRecentHandlerMessages:
    def test_malformed_entries_are_skipped(self):
        redis_conn = MagicMock()
        redis_conn.xrevrange.return_value = [
            *_malformed_entries(),
            _entry(_completed()),
            _entry(_completed(handler="OtherHandler")),
        ]

        messages = handlers_module.collect_recent_messages(redis_conn, "OrderHandler")

        assert [m["handler"] for m in messages] == ["OrderHandler"]

    def test_an_error_after_decoding_reaches_the_caller(self, monkeypatch):
        monkeypatch.setattr(handlers_module, "_decode_stream_id", _raise_type_error)
        redis_conn = MagicMock()
        redis_conn.xrevrange.return_value = [_entry(_completed())]

        with pytest.raises(TypeError, match="bug after decoding"):
            handlers_module.collect_recent_messages(redis_conn, "OrderHandler")


class TestProcessManagerTraceMetrics:
    def test_malformed_entries_are_skipped(self):
        redis_conn = MagicMock()
        redis_conn.xrange.return_value = [
            *_malformed_entries(),
            _entry(_completed(handler="OrderPM")),
            _entry(_completed(handler="OrderPM", duration_ms="slow")),
            _entry(_failed(handler="OrderPM")),
            _entry(_completed(handler=["not", "a", "str"])),
            _entry(_completed(handler="OrderPM", event=["not", "a", "str"])),
        ]

        metrics = processes_module.collect_pm_trace_metrics(
            redis_conn, {"OrderPM"}, 300_000
        )

        assert metrics["OrderPM"]["processed"] == 2
        assert metrics["OrderPM"]["failed"] == 1
        assert metrics["OrderPM"]["avg_latency_ms"] == 10.0

    def test_an_error_after_decoding_reaches_the_caller(self, monkeypatch):
        monkeypatch.setattr(processes_module, "trace_number", _raise_type_error)
        redis_conn = MagicMock()
        redis_conn.xrange.return_value = [_entry(_completed(handler="OrderPM"))]

        with pytest.raises(TypeError, match="bug after decoding"):
            processes_module.collect_pm_trace_metrics(redis_conn, {"OrderPM"}, 300_000)


class TestCorrelationTraces:
    def test_malformed_entries_are_skipped(self):
        redis_conn = MagicMock()
        redis_conn.xrange.return_value = [
            *_malformed_entries(),
            _entry(_completed(correlation_id="corr-1", message_id="m-1")),
            _entry(_completed(correlation_id="corr-1", message_id=["m", "2"])),
        ]

        traces = _load_traces_for_correlation(
            [_domain_with_redis(redis_conn)], "corr-1"
        )

        assert traces == {"m-1": {"handler": "OrderHandler", "duration_ms": 10.0}}

    def test_an_error_after_decoding_reaches_the_caller(self, monkeypatch):
        class BrokenTrace(dict):
            def get(self, key, default=None):
                if key == "message_id":
                    raise TypeError("bug after decoding")
                return super().get(key, default)

        monkeypatch.setattr(
            timeline_module,
            "decode_trace",
            lambda fields: BrokenTrace(_completed(correlation_id="corr-1")),
        )
        redis_conn = MagicMock()
        redis_conn.xrange.return_value = [_entry(_completed(correlation_id="corr-1"))]

        with pytest.raises(TypeError, match="bug after decoding"):
            _load_traces_for_correlation([_domain_with_redis(redis_conn)], "corr-1")


@pytest.mark.no_test_domain
class TestSseTraceFeed:
    @staticmethod
    def _sent_traces(monkeypatch, messages: list, path: str = "/stream") -> list:
        pending = list(messages)

        # The test client only returns once the stream ends, so the fake
        # client disconnects when the feed has no messages left.
        async def is_disconnected(self):
            return not pending

        monkeypatch.setattr(Request, "is_disconnected", is_disconnected)
        redis_conn = MagicMock()
        redis_conn.pubsub.return_value.get_message.side_effect = lambda **kwargs: (
            pending.pop(0)
        )

        response = _client(redis_conn).get(path)

        return [
            json.loads(line[len("data: ") :])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]

    def test_malformed_messages_are_skipped(self, monkeypatch):
        def message(data):
            return {"type": "message", "data": data}

        sent = self._sent_traces(
            monkeypatch,
            [
                message(b"{not json"),
                message(b"[1, 2]"),
                message(b"\xff\xfe"),
                message(json.dumps(_completed()).encode()),
            ],
        )

        assert [t["event"] for t in sent] == ["handler.completed"]

    def test_a_non_str_value_does_not_match_a_filter(self, monkeypatch):
        sent = self._sent_traces(
            monkeypatch,
            [
                {"type": "message", "data": json.dumps(_completed(event=["x"]))},
                {"type": "message", "data": json.dumps(_completed())},
            ],
            path="/stream?event=handler.*",
        )

        assert [t["event"] for t in sent] == ["handler.completed"]

    def test_an_error_after_decoding_reaches_the_caller(self, monkeypatch):
        monkeypatch.setattr(sse_module, "_format_sse", _raise_type_error)

        with pytest.raises(TypeError, match="bug after decoding"):
            self._sent_traces(
                monkeypatch,
                [{"type": "message", "data": json.dumps(_completed()).encode()}],
            )
