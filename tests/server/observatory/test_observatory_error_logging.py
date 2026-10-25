"""Observatory scrapes log the Redis, outbox and domain-graph errors they skip.

Each scrape is best-effort: a failure on one domain, stream or group must not
break the endpoint. These tests force the failure and check two things: the
endpoint still returns its fallback, and a log record names what was skipped.
"""

import json
import logging
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from protean import Domain
from protean.server.observatory import Observatory
from protean.server.observatory.api import _get_redis as api_get_redis
from protean.server.observatory.metrics import _hand_rolled_metrics, _scrape_cache
from protean.server.observatory.routes import domain as domain_routes
from protean.server.observatory.routes.handlers import _get_redis as handlers_get_redis
from protean.server.observatory.routes.processes import (
    _get_redis as processes_get_redis,
)
from protean.server.observatory.routes.timeline import _load_traces_for_correlation

_REDIS_BROKER = {"provider": "redis", "URI": "redis://127.0.0.1:56379/2"}


def _domain(name: str, broker: dict) -> Domain:
    domain = Domain(name=name, config={"brokers": {"default": broker}})
    domain.init(traverse=False)
    return domain


def _failing_domain(name: str = "broken") -> Domain:
    """A real domain whose broker lookup raises, as when a broker fails to start."""
    domain = _domain(name, {"provider": "inline"})

    def _raise(*args, **kwargs):
        raise RuntimeError("broker init failed")

    domain.brokers.get = _raise
    return domain


def _domain_with_redis(name: str = "test") -> tuple[Domain, MagicMock]:
    """A real domain on the Redis broker, with a fake Redis client under it.

    The client is never connected; every Redis call goes to the fake.
    """
    domain = _domain(name, _REDIS_BROKER)
    redis_conn = MagicMock()
    domain.brokers.get("default").redis_instance = redis_conn
    redis_conn.scan.return_value = (0, [b"orders::order"])
    redis_conn.xrange.return_value = []
    return domain, redis_conn


def _fail_outbox(domain: Domain) -> None:
    """Make the domain's outbox query raise, as when its database is down."""

    def _raise(*args, **kwargs):
        raise RuntimeError("no outbox")

    domain._get_outbox_repo = _raise


def _records(caplog, logger_name: str, message: str) -> list[logging.LogRecord]:
    return [
        r for r in caplog.records if r.name == logger_name and r.getMessage() == message
    ]


def _assert_one_debug(caplog, logger_name: str, message: str, error: str) -> None:
    records = _records(caplog, logger_name, message)
    assert len(records) == 1, [r.getMessage() for r in caplog.records]
    assert records[0].levelno == logging.DEBUG
    assert records[0].exc_info is not None
    assert str(records[0].exc_info[1]) == error


@pytest.mark.no_test_domain
class TestBrokerLookupLogsSkippedDomain:
    @pytest.mark.parametrize(
        "get_redis, logger_name",
        [
            (api_get_redis, "protean.server.observatory.api"),
            (handlers_get_redis, "protean.server.observatory.routes.handlers"),
            (processes_get_redis, "protean.server.observatory.routes.processes"),
        ],
    )
    def test_failing_domain_is_logged_and_next_domain_used(
        self, caplog, get_redis, logger_name
    ):
        caplog.set_level(logging.DEBUG, logger=logger_name)
        good, redis_conn = _domain_with_redis()

        assert get_redis([_failing_domain(), good]) is redis_conn
        _assert_one_debug(
            caplog,
            logger_name,
            "Could not get the Redis broker of domain broken",
            "broker init failed",
        )

    @pytest.mark.parametrize(
        "get_redis, logger_name",
        [
            (api_get_redis, "protean.server.observatory.api"),
            (handlers_get_redis, "protean.server.observatory.routes.handlers"),
            (processes_get_redis, "protean.server.observatory.routes.processes"),
        ],
    )
    def test_no_record_when_lookup_succeeds(self, caplog, get_redis, logger_name):
        caplog.set_level(logging.DEBUG, logger=logger_name)
        good, redis_conn = _domain_with_redis()

        assert get_redis([good]) is redis_conn
        assert not [r for r in caplog.records if r.name == logger_name]

    def test_timeline_trace_load_logs_failing_domain(self, caplog):
        logger_name = "protean.server.observatory.routes.timeline"
        caplog.set_level(logging.DEBUG, logger=logger_name)

        assert _load_traces_for_correlation([_failing_domain()], "corr-1") == {}
        _assert_one_debug(
            caplog,
            logger_name,
            "Could not get the Redis broker of domain broken",
            "broker init failed",
        )

    def test_timeline_trace_load_logs_nothing_when_lookup_succeeds(self, caplog):
        logger_name = "protean.server.observatory.routes.timeline"
        caplog.set_level(logging.DEBUG, logger=logger_name)
        good, _ = _domain_with_redis()

        assert _load_traces_for_correlation([good], "corr-1") == {}
        assert not [r for r in caplog.records if r.name == logger_name]

    def test_sse_stream_logs_nothing_when_lookup_does_not_raise(self, caplog):
        logger_name = "protean.server.observatory.sse"
        caplog.set_level(logging.DEBUG, logger=logger_name)
        # The broker lookup succeeds but finds no Redis broker
        domain = _domain("no-redis", {"provider": "inline"})
        client = TestClient(Observatory(domains=[domain]).app)

        with client.stream("GET", "/stream") as response:
            data = None
            for line in response.iter_lines():
                if line.startswith("data: "):
                    data = json.loads(line[len("data: ") :])
                    break

        assert data == {"error": "Redis not available"}
        assert not [r for r in caplog.records if r.name == logger_name]

    def test_sse_stream_logs_failing_domain(self, caplog):
        logger_name = "protean.server.observatory.sse"
        caplog.set_level(logging.DEBUG, logger=logger_name)
        client = TestClient(Observatory(domains=[_failing_domain()]).app)

        with client.stream("GET", "/stream") as response:
            assert response.status_code == 200
            data = None
            for line in response.iter_lines():
                if line.startswith("data: "):
                    data = json.loads(line[len("data: ") :])
                    break

        assert data == {"error": "Redis not available"}
        _assert_one_debug(
            caplog,
            logger_name,
            "Could not get the Redis broker of domain broken",
            "broker init failed",
        )


@pytest.mark.no_test_domain
class TestApiStreamScrapesLogSkippedStream:
    logger_name = "protean.server.observatory.api"

    def _client(self, domain: Domain) -> TestClient:
        return TestClient(Observatory(domains=[domain]).app)

    @pytest.mark.parametrize("path", ["/api/streams", "/api/stats"])
    def test_stream_read_failure_is_logged(self, caplog, path):
        caplog.set_level(logging.DEBUG, logger=self.logger_name)
        domain, redis_conn = _domain_with_redis()
        redis_conn.xlen.side_effect = RuntimeError("redis down")

        response = self._client(domain).get(path)

        assert response.status_code == 200
        assert response.json()["message_counts"]["total_messages"] == 0
        _assert_one_debug(
            caplog,
            self.logger_name,
            "Could not read stream orders::order",
            "redis down",
        )

    @pytest.mark.parametrize("path", ["/api/consumers", "/api/workers"])
    def test_group_read_failure_is_logged(self, caplog, path):
        caplog.set_level(logging.DEBUG, logger=self.logger_name)
        domain, redis_conn = _domain_with_redis()
        redis_conn.xinfo_groups.side_effect = RuntimeError("redis down")

        response = self._client(domain).get(path)

        assert response.status_code == 200
        assert response.json()["count"] == 0
        _assert_one_debug(
            caplog,
            self.logger_name,
            "Could not read groups of stream orders::order",
            "redis down",
        )

    @pytest.mark.parametrize("path", ["/api/consumers", "/api/workers"])
    def test_consumer_read_failure_is_logged(self, caplog, path):
        caplog.set_level(logging.DEBUG, logger=self.logger_name)
        domain, redis_conn = _domain_with_redis()
        redis_conn.xinfo_groups.return_value = [
            {"name": "Handler", "pending": 0, "lag": 0}
        ]
        redis_conn.xinfo_consumers.side_effect = RuntimeError("redis down")

        response = self._client(domain).get(path)

        assert response.status_code == 200
        assert response.json()["count"] == 0
        _assert_one_debug(
            caplog,
            self.logger_name,
            "Could not read consumers of group Handler on stream orders::order",
            "redis down",
        )

    def test_queue_depth_group_failure_keeps_stream_and_is_logged(self, caplog):
        caplog.set_level(logging.DEBUG, logger=self.logger_name)
        domain, redis_conn = _domain_with_redis()
        redis_conn.xlen.return_value = 7
        redis_conn.xinfo_groups.side_effect = RuntimeError("redis down")

        response = self._client(domain).get("/api/queue-depth")

        assert response.status_code == 200
        stream = response.json()["streams"]["orders::order"]
        assert stream == {"length": 7, "consumer_groups": {}}
        _assert_one_debug(
            caplog,
            self.logger_name,
            "Could not read groups of stream orders::order",
            "redis down",
        )

    def test_queue_depth_stream_failure_is_logged(self, caplog):
        caplog.set_level(logging.DEBUG, logger=self.logger_name)
        domain, redis_conn = _domain_with_redis()
        redis_conn.xlen.side_effect = RuntimeError("redis down")

        response = self._client(domain).get("/api/queue-depth")

        assert response.status_code == 200
        assert response.json()["streams"] == {}
        _assert_one_debug(
            caplog,
            self.logger_name,
            "Could not read stream orders::order",
            "redis down",
        )

    def test_outbox_failure_drops_domain_and_is_logged(self, caplog):
        caplog.set_level(logging.DEBUG, logger=self.logger_name)
        domain, redis_conn = _domain_with_redis()
        redis_conn.xlen.return_value = 0
        redis_conn.xinfo_groups.return_value = []
        _fail_outbox(domain)

        response = self._client(domain).get("/api/queue-depth")

        assert response.status_code == 200
        assert response.json()["outbox"] == {}
        records = _records(caplog, self.logger_name, "Error querying outbox for test")
        assert len(records) == 1
        assert records[0].levelno == logging.ERROR
        assert str(records[0].exc_info[1]) == "no outbox"

    def test_no_record_when_scrape_succeeds(self, caplog):
        caplog.set_level(logging.DEBUG, logger=self.logger_name)
        domain, redis_conn = _domain_with_redis()
        redis_conn.xlen.return_value = 3
        redis_conn.xinfo_groups.return_value = [
            {"name": "Handler", "pending": 1, "lag": 2}
        ]
        redis_conn.xinfo_consumers.return_value = [
            {"name": "Handler-host-1-abc", "pending": 1, "idle": 0}
        ]
        client = self._client(domain)

        for path in [
            "/api/streams",
            "/api/stats",
            "/api/consumers",
            "/api/workers",
            "/api/queue-depth",
        ]:
            assert client.get(path).status_code == 200

        assert not [
            r
            for r in caplog.records
            if r.name == self.logger_name and r.getMessage().startswith("Could not")
        ]


@pytest.mark.no_test_domain
class TestConsumerMetricsLogSkippedStream:
    logger_name = "protean.server.observatory.metrics"

    def test_group_read_failure_is_logged(self, caplog):
        caplog.set_level(logging.DEBUG, logger=self.logger_name)
        domain, redis_conn = _domain_with_redis()
        redis_conn.xinfo_groups.side_effect = RuntimeError("redis down")

        body = _hand_rolled_metrics([domain])

        assert "# TYPE protean_consumer_pending gauge" in body
        assert "protean_consumer_pending{" not in body
        _assert_one_debug(
            caplog,
            self.logger_name,
            "Metrics: could not read groups of stream orders::order",
            "redis down",
        )

    def test_consumer_read_failure_is_logged(self, caplog):
        caplog.set_level(logging.DEBUG, logger=self.logger_name)
        domain, redis_conn = _domain_with_redis()
        redis_conn.xinfo_groups.return_value = [
            {"name": "Handler", "pending": 0, "lag": 0}
        ]
        redis_conn.xinfo_consumers.side_effect = RuntimeError("redis down")

        body = _hand_rolled_metrics([domain])

        assert "protean_consumer_pending{" not in body
        _assert_one_debug(
            caplog,
            self.logger_name,
            "Metrics: could not read consumers of group Handler on stream "
            "orders::order",
            "redis down",
        )

    def test_no_record_when_scrape_succeeds(self, caplog):
        caplog.set_level(logging.DEBUG, logger=self.logger_name)
        domain, redis_conn = _domain_with_redis()
        redis_conn.xinfo_groups.return_value = [
            {"name": "Handler", "pending": 1, "lag": 0}
        ]
        redis_conn.xinfo_consumers.return_value = [
            {"name": "Handler-host-1-abc", "pending": 1, "idle": 0}
        ]

        body = _hand_rolled_metrics([domain])

        assert "protean_consumer_pending{" in body
        assert not [
            r
            for r in caplog.records
            if r.name == self.logger_name
            and r.getMessage().startswith("Metrics: could not read")
        ]

    def test_outbox_failure_is_logged(self, caplog):
        caplog.set_level(logging.DEBUG, logger=self.logger_name)
        domain = _domain("no-redis", {"provider": "inline"})
        _fail_outbox(domain)
        # The metrics module caches collections for a few seconds across calls,
        # so an earlier test's Redis broker would leak into this output.
        _scrape_cache.clear()

        body = _hand_rolled_metrics([domain])

        assert "protean_outbox_pending_count{" not in body
        assert "protean_broker_pool_active_connections" not in body
        assert _records(
            caplog,
            self.logger_name,
            "Metrics: outbox query failed for no-redis: no outbox",
        )


@pytest.mark.no_test_domain
class TestDomainGraphBuildFailureIsLogged:
    def test_failing_ir_build_is_logged(self, caplog, monkeypatch):
        logger_name = domain_routes.__name__
        caplog.set_level(logging.WARNING, logger=logger_name)
        domain = _domain("broken-ir", {"provider": "inline"})

        def _raise(self):
            raise RuntimeError("boom")

        monkeypatch.setattr(domain_routes.IRBuilder, "build", _raise)

        Observatory(domains=[domain])

        records = _records(caplog, logger_name, "Failed to build domain IR graph")
        assert len(records) == 1
        assert str(records[0].exc_info[1]) == "boom"
