"""Observatory API responses for inputs the main endpoint tests leave out.

These run in the core lane. Where an endpoint reads Redis, the domain's Redis
broker gets a stand-in redis-py client whose replies each test sets, so a test
can return shapes a real server rarely sends (non-dict ``XINFO`` entries, trace
IDs outside the window).
"""

import json
import time
from unittest.mock import MagicMock

import pytest
import redis
from fastapi import FastAPI
from fastapi.testclient import TestClient

import protean.server.observatory.api as api_module
from protean import Domain
from protean.server.observatory import Observatory
from protean.server.observatory.api import create_api_router


def _stand_in_redis(domain: Domain) -> MagicMock:
    redis_conn = MagicMock(spec=redis.Redis)
    domain.brokers["default"]._adapter.get_connection = lambda: redis_conn
    return redis_conn


def _client(domain: Domain) -> TestClient:
    return TestClient(Observatory(domains=[domain]).app)


def _router_client(domain: Domain) -> TestClient:
    app = FastAPI()
    app.include_router(create_api_router([domain]))
    return TestClient(app)


def _trace_entry(trace: dict, ts_ms: int) -> tuple[bytes, dict]:
    return f"{ts_ms}-0".encode(), {b"data": json.dumps(trace).encode()}


@pytest.fixture
def no_redis(monkeypatch):
    monkeypatch.setattr(api_module, "_get_redis", lambda domains: None)


class TestConsumerGroupsThatAreNotMappings:
    def test_consumers_skip_a_group_entry_that_is_not_a_dict(self, test_domain):
        redis_conn = _stand_in_redis(test_domain)
        redis_conn.scan.return_value = (0, [b"orders"])
        redis_conn.xinfo_groups.return_value = ["junk", {"name": b"Handler"}]
        redis_conn.xinfo_consumers.return_value = [
            {b"name": b"Handler-host-1-abc", b"pending": 2, b"idle": 7}
        ]

        data = _client(test_domain).get("/api/consumers").json()

        assert data == {
            "consumers": [
                {
                    "consumer_name": "Handler-host-1-abc",
                    "group": "Handler",
                    "stream": "orders",
                    "pending": 2,
                    "idle_ms": 7,
                }
            ],
            "count": 1,
        }
        redis_conn.xinfo_consumers.assert_called_once_with("orders", "Handler")

    def test_queue_depth_skips_a_group_entry_that_is_not_a_dict(self, test_domain):
        redis_conn = _stand_in_redis(test_domain)
        redis_conn.scan.return_value = (0, [b"orders"])
        redis_conn.xlen.return_value = 4
        redis_conn.xinfo_groups.return_value = [
            "junk",
            {"name": "Handler", "pending": 1, "lag": 3},
        ]

        data = _client(test_domain).get("/api/queue-depth").json()

        assert data["streams"]["orders"] == {
            "length": 4,
            "consumer_groups": {"Handler": {"pending": 1, "lag": 3}},
        }
        assert data["totals"]["consumer_pending"] == 1
        assert data["totals"]["stream_depth"] == 3

    def test_consumers_skip_a_consumer_entry_that_is_not_a_dict(self, test_domain):
        redis_conn = _stand_in_redis(test_domain)
        redis_conn.scan.return_value = (0, [b"orders"])
        redis_conn.xinfo_groups.return_value = [{"name": b"Handler"}]
        redis_conn.xinfo_consumers.return_value = [
            "junk",
            {b"name": b"Handler-host-1-abc", b"pending": 2, b"idle": 7},
        ]

        data = _client(test_domain).get("/api/consumers").json()

        assert [c["consumer_name"] for c in data["consumers"]] == ["Handler-host-1-abc"]
        assert data["count"] == 1


class TestGroupNameThatIsNotUtf8:
    """``/streams`` stops counting a stream at a group name that fails to decode.

    ``/stats`` never reads group names, so it counts every group.
    """

    def _redis_with_bad_group_name(self, domain: Domain) -> MagicMock:
        redis_conn = _stand_in_redis(domain)
        redis_conn.scan.return_value = (0, [b"orders"])
        redis_conn.xlen.return_value = 5
        redis_conn.xinfo_groups.return_value = [
            {"name": "Good", "pending": 1, "lag": 0},
            {"name": b"\xff\xfe", "pending": 2, "lag": 0},
            {"name": "After", "pending": 4, "lag": 0},
        ]
        return redis_conn

    def test_streams_leaves_out_the_group_it_cannot_name(self, test_domain):
        self._redis_with_bad_group_name(test_domain)

        data = _client(test_domain).get("/api/streams").json()

        assert data["message_counts"]["in_flight"] == 1
        assert data["consumer_groups"] == {
            "Good": {"stream": "orders", "pending": 1, "lag": 0}
        }

    def test_stats_counts_the_group_it_cannot_name(self, test_domain):
        self._redis_with_bad_group_name(test_domain)

        data = _client(test_domain).get("/api/stats").json()

        assert data["message_counts"]["in_flight"] == 7
        assert data["message_counts"]["total_messages"] == 5


class TestWorkers:
    def _client_with_consumer(
        self, domain: Domain, group: str, traces: list[tuple[bytes, dict]]
    ) -> TestClient:
        redis_conn = _stand_in_redis(domain)
        redis_conn.scan.return_value = (0, [b"orders"])
        redis_conn.xinfo_groups.return_value = [{"name": group}]
        redis_conn.xinfo_consumers.return_value = [
            {"name": "Handler-host1-1000-abc", "pending": 0, "idle": 1000}
        ]
        redis_conn.xrange.return_value = traces
        return _client(domain)

    def test_a_protean_group_adds_no_engine_domain(self, test_domain):
        client = self._client_with_consumer(
            test_domain, "protean.server.engine.Commands", []
        )

        workers = client.get("/api/workers").json()["workers"]

        assert len(workers) == 1
        assert workers[0]["domain"] == ""
        assert workers[0]["streams"] == ["orders"]

    def test_an_application_group_adds_its_top_package_as_the_domain(self, test_domain):
        client = self._client_with_consumer(
            test_domain, "inventory.projections.Projector", []
        )

        workers = client.get("/api/workers").json()["workers"]

        assert [w["domain"] for w in workers] == ["inventory"]

    def test_a_trace_after_the_window_counts_in_no_bucket(self, test_domain):
        completed = {
            "event": "handler.completed",
            "worker_id": "Handler-host1-1000-abc",
        }
        future_ms = int(time.time() * 1000) + 60_000
        client = self._client_with_consumer(
            test_domain, "Handler", [_trace_entry(completed, future_ms)]
        )

        workers = client.get("/api/workers").json()["workers"]

        assert len(workers) == 1
        assert workers[0]["worker_id"] == "host1-1000"
        assert workers[0]["throughput"]["total"] == 0


class TestOverviewCache:
    def _scan_counter(self, domain: Domain) -> MagicMock:
        redis_conn = _stand_in_redis(domain)
        completed = {"event": "handler.completed", "duration_ms": 4.0}
        redis_conn.xrange.return_value = [
            _trace_entry(completed, int(time.time() * 1000))
        ]
        return redis_conn

    def test_a_second_overview_request_is_served_from_the_cache(self, test_domain):
        redis_conn = self._scan_counter(test_domain)
        client = _router_client(test_domain)

        first = client.get("/traces/overview?window=5m").json()
        second = client.get("/traces/overview?window=5m").json()

        assert first["total"] == 1
        assert second == first
        assert redis_conn.xrange.call_count == 1

    def test_stats_and_timeline_reuse_the_overview_scan(self, test_domain):
        redis_conn = self._scan_counter(test_domain)
        client = _router_client(test_domain)

        overview = client.get("/traces/overview?window=5m").json()
        stats = client.get("/traces/stats?window=5m").json()
        timeline = client.get("/traces/timeline?window=5m").json()

        assert redis_conn.xrange.call_count == 1
        assert stats == {
            "window": "5m",
            "counts": {"handler.completed": 1},
            "error_count": 0,
            "error_rate": 0.0,
            "avg_latency_ms": 4.0,
            "total": 1,
        }
        assert timeline == {
            "window": "5m",
            "bucket_ms": overview["bucket_ms"],
            "buckets": overview["buckets"],
        }

    def test_each_router_keeps_its_own_cache(self, test_domain):
        redis_conn = self._scan_counter(test_domain)
        client_a = _router_client(test_domain)
        client_b = _router_client(test_domain)

        client_a.get("/traces/overview?window=5m")
        client_b.get("/traces/overview?window=5m")

        assert redis_conn.xrange.call_count == 2

    def test_a_different_window_is_not_served_from_the_cache(self, test_domain):
        redis_conn = self._scan_counter(test_domain)
        client = _router_client(test_domain)

        client.get("/traces/overview?window=5m")
        client.get("/traces/overview?window=1h")

        assert redis_conn.xrange.call_count == 2

    def test_stats_returns_the_overview_error_unchanged(self, test_domain):
        response = _router_client(test_domain).get("/traces/stats?window=2m")

        assert response.status_code == 400
        assert response.json() == {
            "error": "Invalid window: 2m. Use 5m, 15m, 1h, 24h, 7d."
        }


class TestFailedTraceRange:
    def test_an_invalid_custom_range_is_a_bad_request(self, test_domain):
        redis_conn = _stand_in_redis(test_domain)

        response = _client(test_domain).get(
            "/api/traces/failed?start=yesterday&end=today"
        )

        assert response.status_code == 400
        assert response.json() == {"error": "Invalid date format. Use ISO 8601."}
        redis_conn.xrange.assert_not_called()

    def test_an_invalid_window_is_a_bad_request(self, test_domain):
        redis_conn = _stand_in_redis(test_domain)

        response = _client(test_domain).get("/api/traces/failed?window=2m")

        assert response.status_code == 400
        assert response.json() == {
            "error": "Invalid window: 2m. Use 5m, 15m, 1h, 24h, 7d."
        }
        redis_conn.xrange.assert_not_called()

    def test_a_custom_range_reads_between_its_millisecond_ids(self, test_domain):
        redis_conn = _stand_in_redis(test_domain)
        redis_conn.xrange.return_value = []

        response = _client(test_domain).get(
            "/api/traces/failed"
            "?start=2026-01-01T00:00:00%2B00:00&end=2026-01-01T00:00:01%2B00:00"
        )

        assert response.status_code == 200
        redis_conn.xrange.assert_called_once_with(
            "protean:traces", min="1767225600000", max="1767225601000"
        )

    def test_a_start_without_an_end_falls_back_to_the_window(self, test_domain):
        redis_conn = _stand_in_redis(test_domain)
        redis_conn.xrange.return_value = []
        before_ms = int(time.time() * 1000)

        _client(test_domain).get(
            "/api/traces/failed?window=5m&start=2026-01-01T00:00:00"
        )

        kwargs = redis_conn.xrange.call_args.kwargs
        assert kwargs["max"] == "+"
        assert int(kwargs["min"]) >= before_ms - 5 * 60 * 1000


class TestTraceDetail:
    def test_an_unknown_stream_id_is_not_found(self, test_domain):
        redis_conn = _stand_in_redis(test_domain)
        redis_conn.xrange.return_value = []

        response = _client(test_domain).get("/api/traces/1-0")

        assert response.status_code == 404
        assert response.json() == {"error": "Trace not found"}


class TestRedisNotAvailable:
    @pytest.mark.parametrize(
        "path, body",
        [
            pytest.param(
                "/api/traces/failed",
                {"traces": [], "total_count": 0, "error": "Redis not available"},
                id="failed_traces",
            ),
            pytest.param(
                "/api/traces/1-0", {"error": "Redis not available"}, id="trace_detail"
            ),
        ],
    )
    def test_the_endpoint_answers_503(self, test_domain, no_redis, path, body):
        response = _client(test_domain).get(path)

        assert response.status_code == 503
        assert response.json() == body
