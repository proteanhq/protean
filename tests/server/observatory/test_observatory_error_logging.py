"""Observatory scrapes log the Redis errors they skip.

Each scrape is best-effort: a failure on one domain, stream or group must not
break the endpoint. These tests force the failure and check two things: the
endpoint still returns its fallback, and a debug record names what was skipped.
"""

import json
import logging
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from protean.server.observatory import Observatory
from protean.server.observatory.api import _get_redis as api_get_redis
from protean.server.observatory.metrics import _hand_rolled_metrics
from protean.server.observatory.routes.handlers import _get_redis as handlers_get_redis
from protean.server.observatory.routes.processes import (
    _get_redis as processes_get_redis,
)
from protean.server.observatory.routes.timeline import _load_traces_for_correlation


def _mock_domain(name: str) -> MagicMock:
    mock = MagicMock()
    mock.name = name
    mock.domain_context.return_value.__enter__ = MagicMock(return_value=None)
    mock.domain_context.return_value.__exit__ = MagicMock(return_value=False)
    return mock


def _failing_domain(name: str = "broken") -> MagicMock:
    domain = _mock_domain(name)
    domain.brokers.get.side_effect = RuntimeError("broker init failed")
    return domain


def _domain_with_redis(name: str = "test") -> tuple[MagicMock, MagicMock]:
    domain = _mock_domain(name)
    broker = MagicMock()
    redis_conn = MagicMock()
    broker.redis_instance = redis_conn
    domain.brokers.get.return_value = broker
    domain._get_outbox_repo.side_effect = RuntimeError("no outbox")
    redis_conn.scan.return_value = (0, [b"orders::order"])
    redis_conn.xrange.return_value = []
    return domain, redis_conn


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

    def _client(self, domain: MagicMock) -> TestClient:
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
