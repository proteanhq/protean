"""Tests for Observatory /api/subscriptions endpoint and Prometheus metrics.

Integration tests require a running Redis instance and are gated behind
@pytest.mark.redis. The other tests build a real domain whose subscriptions
read lag from the memory event store and from a fake Redis client, so they
need no infrastructure.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.event_handler import BaseEventHandler
from protean.server.observatory import Observatory
from protean.utils import fqn
from tests.shared import FrozenClock


@pytest.fixture(autouse=True)
def _clear_scrape_cache():
    """Clear the per-scrape metrics cache between tests."""
    from protean.server.observatory.metrics import _scrape_cache

    _scrape_cache.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

T0 = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)


class _StatusDomain:
    """A real domain whose subscriptions report the lag a test sets up.

    Stream subscriptions read their consumer group and DLQ length from Redis,
    so a fake Redis client stands in for the server. Event-store
    subscriptions read their position and the stream head from the memory
    event store. The default subscription type stays ``event_store``, so the
    domain runs no outbox processor and reports only the handlers a test adds.
    """

    def __init__(self, name: str, *, redis: bool = True) -> None:
        """``redis=False`` keeps the default inline broker, which has no Redis
        client at all."""
        config = (
            {
                "brokers": {
                    "default": {
                        "provider": "redis",
                        "URI": "redis://127.0.0.1:1/0",
                    }
                }
            }
            if redis
            else {}
        )
        self.domain = Domain(name=name, config=config)
        self._redis = redis
        self.clock = FrozenClock(T0)
        self.domain.clock = self.clock

        @self.domain.aggregate
        class Order(BaseAggregate):
            pass

        self._aggregate = Order
        self._groups: dict[str, list[dict]] = {}
        self._lengths: dict[str, int] = {}
        self._event_store_writes: list[tuple[type, str, int, int | None]] = []

    def stream_handler(
        self,
        name: str,
        stream: str,
        *,
        lag: int = 0,
        pending: int = 0,
        dlq: int = 0,
        in_group: bool = True,
    ) -> type:
        """Add a stream subscription. ``in_group=False`` leaves its consumer
        group missing in Redis, so its lag cannot be read."""
        handler_cls = type(name, (BaseEventHandler,), {})
        self.domain.event_handler(
            handler_cls,
            part_of=self._aggregate,
            stream_category=stream,
            subscription_type="stream",
        )
        if in_group:
            self._groups.setdefault(stream, []).append(
                {
                    "name": fqn(handler_cls).encode(),
                    "pending": pending,
                    "lag": lag,
                    "consumers": 2,
                    "last-delivered-id": b"1700000000000-0",
                }
            )
        self._lengths[f"{stream}:dlq"] = dlq
        return handler_cls

    def event_store_handler(
        self, name: str, stream: str, *, events: int, position: int | None
    ) -> type:
        """Add an event-store subscription on a category holding ``events``
        events. ``position=None`` means it has never written a position."""
        handler_cls = type(name, (BaseEventHandler,), {})
        self.domain.event_handler(
            handler_cls,
            part_of=self._aggregate,
            stream_category=stream,
            subscription_type="event_store",
        )
        self._event_store_writes.append((handler_cls, stream, events, position))
        return handler_cls

    def build(self) -> Domain:
        self.domain.init(traverse=False)
        fake_redis = MagicMock()
        fake_redis.xinfo_groups.side_effect = lambda stream: self._groups.get(
            stream, []
        )
        fake_redis.xlen.side_effect = lambda key: self._lengths.get(key, 0)
        with self.domain.domain_context():
            if self._redis:
                self.domain.brokers.get("default").redis_instance = fake_redis
            store = self.domain.event_store.store
            for handler_cls, stream, events, position in self._event_store_writes:
                for i in range(events):
                    store._write(f"{stream}-{i}", "Placed", {"i": i})
                if position is not None:
                    store._write(
                        f"position-{fqn(handler_cls)}-{stream}",
                        "Read",
                        {"position": position},
                    )
        return self.domain


def _get(domain: Domain, path: str):
    return TestClient(Observatory(domains=[domain]).app).get(path)


# ---------------------------------------------------------------------------
# Integration tests (require Redis)
# ---------------------------------------------------------------------------


@pytest.fixture
def observatory(test_domain):
    """Observatory backed by a real domain."""
    return Observatory(domains=[test_domain])


@pytest.fixture
def client(observatory):
    return TestClient(observatory.app)


@pytest.mark.redis
class TestSubscriptionsEndpoint:
    def test_returns_200(self, client):
        """GET /api/subscriptions returns 200."""
        response = client.get("/api/subscriptions")
        assert response.status_code == 200

    def test_response_keyed_by_domain(self, client, test_domain):
        """Response is keyed by domain name."""
        response = client.get("/api/subscriptions")
        data = response.json()
        assert test_domain.name in data

    def test_domain_entry_has_status(self, client, test_domain):
        """Each domain entry has a status field."""
        response = client.get("/api/subscriptions")
        data = response.json()
        assert "status" in data[test_domain.name]

    def test_domain_entry_has_summary(self, client, test_domain):
        """Each domain entry has a summary with counts."""
        response = client.get("/api/subscriptions")
        data = response.json()
        domain_data = data[test_domain.name]
        if domain_data["status"] == "ok":
            assert "summary" in domain_data
            assert "total" in domain_data["summary"]


# ---------------------------------------------------------------------------
# Endpoint tests without infrastructure
# ---------------------------------------------------------------------------


class TestSubscriptionsEndpointUnit:
    def test_returns_subscription_list(self):
        """Endpoint returns subscriptions with lag data."""
        setup = _StatusDomain("test-domain")
        setup.stream_handler("TestHandler", "test")
        setup.stream_handler("SlowHandler", "order", lag=42, pending=3, dlq=1)
        domain = setup.build()

        response = _get(domain, "/api/subscriptions")

        assert response.status_code == 200
        data = response.json()
        assert "test-domain" in data

        domain_data = data["test-domain"]
        assert domain_data["status"] == "ok"
        assert len(domain_data["subscriptions"]) == 2

        summary = domain_data["summary"]
        assert summary["total"] == 2
        assert summary["ok"] == 1
        assert summary["lagging"] == 1
        assert summary["total_lag"] == 42
        assert summary["total_pending"] == 3
        assert summary["total_dlq"] == 1

    def test_subscription_carries_position_stream(self):
        """The event-store checkpoint stream flows through /api/subscriptions; a
        non-event-store subscription reports it as null."""
        setup = _StatusDomain("test-domain")
        projector = setup.event_store_handler(
            "OrderProjector", "order", events=3, position=3
        )
        setup.stream_handler("StreamHandler", "test")
        domain = setup.build()

        response = _get(domain, "/api/subscriptions")

        subs = {
            s["handler_name"]: s
            for s in response.json()["test-domain"]["subscriptions"]
        }
        assert subs["OrderProjector"]["position_stream"] == (
            f"position-{fqn(projector)}-order"
        )
        assert subs["StreamHandler"]["position_stream"] is None

    def test_empty_domain_returns_empty_list(self):
        """Domain with no handlers returns empty subscriptions list."""
        domain = _StatusDomain("empty-domain").build()

        response = _get(domain, "/api/subscriptions")

        data = response.json()
        assert data["empty-domain"]["subscriptions"] == []
        assert data["empty-domain"]["summary"]["total"] == 0

    def test_handles_collection_error_gracefully(self):
        """Returns error status when subscription collection fails."""
        domain = _StatusDomain("broken-domain", redis=False).build()

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            side_effect=RuntimeError("collection failed"),
        ):
            response = _get(domain, "/api/subscriptions")

        data = response.json()
        assert data["broken-domain"]["status"] == "error"


# ---------------------------------------------------------------------------
# Prometheus metrics tests
# ---------------------------------------------------------------------------


class TestSubscriptionsMetrics:
    def test_metrics_contains_subscription_lag_help(self):
        """Prometheus output contains subscription lag HELP/TYPE."""
        setup = _StatusDomain("metric-domain")
        setup.stream_handler("SlowHandler", "order", lag=42, pending=3, dlq=1)

        body = _get(setup.build(), "/metrics").text

        assert "# HELP protean_subscription_consumer_lag" in body
        assert "# TYPE protean_subscription_consumer_lag gauge" in body

    def test_metrics_contains_subscription_lag_values(self):
        """Prometheus output contains per-subscription lag values."""
        setup = _StatusDomain("metric-domain")
        setup.stream_handler("OrderHandler", "order", lag=42, pending=3)

        body = _get(setup.build(), "/metrics").text

        assert (
            'protean_subscription_consumer_lag{domain="metric-domain",'
            'handler="OrderHandler",stream="order",type="stream"} 42'
        ) in body

    def test_metrics_contains_subscription_pending(self):
        """Prometheus output includes protean_subscription_pending_messages."""
        setup = _StatusDomain("metric-domain")
        setup.stream_handler("SlowHandler", "order", lag=42, pending=3, dlq=1)

        body = _get(setup.build(), "/metrics").text

        assert (
            'protean_subscription_pending_messages{domain="metric-domain",'
            'handler="SlowHandler",stream="order",type="stream"} 3'
        ) in body

    def test_metrics_contains_subscription_dlq_depth(self):
        """Prometheus output includes protean_subscription_dlq_depth."""
        setup = _StatusDomain("metric-domain")
        setup.stream_handler("SlowHandler", "order", lag=42, pending=3, dlq=1)

        body = _get(setup.build(), "/metrics").text

        assert (
            'protean_subscription_dlq_depth{domain="metric-domain",'
            'handler="SlowHandler",stream="order",type="stream"} 1'
        ) in body

    def test_metrics_contains_subscription_status_gauge(self):
        """Prometheus output includes protean_subscription_status."""
        setup = _StatusDomain("metric-domain")
        setup.stream_handler("TestHandler", "test")

        body = _get(setup.build(), "/metrics").text

        assert (
            'protean_subscription_status{domain="metric-domain",'
            'handler="TestHandler",stream="test",type="stream"} 1'
        ) in body

    def test_metrics_skips_lag_when_none(self):
        """When lag is None, protean_subscription_consumer_lag value line is omitted."""
        setup = _StatusDomain("metric-domain")
        # No consumer group in Redis, so the lag cannot be read.
        setup.stream_handler("UnknownHandler", "test", in_group=False)

        body = _get(setup.build(), "/metrics").text

        # The HELP/TYPE lines should still exist
        assert "# HELP protean_subscription_consumer_lag" in body
        # But no value line for this handler since lag is None
        assert "protean_subscription_consumer_lag{" not in body
        # pending and dlq_depth lines should still appear
        assert 'handler="UnknownHandler"' in body

    def test_metrics_contains_subscription_lag_seconds(self):
        """Prometheus output carries the seconds-behind line when it is known."""
        setup = _StatusDomain("metric-domain")
        setup.event_store_handler("OrderHandler", "order", events=3, position=0)
        domain = setup.build()
        # The position was written at T0; the scrape happens 12.5 s later.
        setup.clock.advance(timedelta(seconds=12.5))

        body = _get(domain, "/metrics").text

        assert "# HELP protean_subscription_lag_seconds" in body
        assert "# TYPE protean_subscription_lag_seconds gauge" in body
        assert (
            'protean_subscription_lag_seconds{domain="metric-domain",'
            'handler="OrderHandler",stream="order",type="event_store"} 12.5'
        ) in body

    def test_metrics_skips_lag_seconds_when_none(self):
        """A subscription with no seconds-behind emits no value line, only HELP/TYPE.

        As with count-based lag, a missing value must not surface as 0.0, which
        would read as caught up."""
        setup = _StatusDomain("metric-domain")
        # A lagging subscription that has never written a position, so there
        # is no time to measure its seconds-behind from.
        setup.event_store_handler("NoSecondsHandler", "order", events=3, position=None)

        body = _get(setup.build(), "/metrics").text

        assert "# HELP protean_subscription_lag_seconds" in body
        # HELP/TYPE carry a trailing space; a value line carries `{labels}`.
        # Its absence proves no seconds value was emitted for this subscription.
        assert "protean_subscription_lag_seconds{" not in body
        # The subscription is still present via its other metric lines.
        assert 'handler="NoSecondsHandler"' in body

    def test_metrics_handles_per_domain_collection_error(self):
        """Per-domain error in collect_subscription_statuses is handled gracefully."""
        domain = _StatusDomain("failing-domain", redis=False).build()

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            side_effect=RuntimeError("collection exploded"),
        ):
            response = _get(domain, "/metrics")

        # Should still return 200 with other metrics
        assert response.status_code == 200
        body = response.text
        # Outbox metrics should still be present
        assert "protean_outbox_pending_count" in body

    def test_metrics_handles_import_error(self):
        """If subscription_status module can't be imported, metrics still works."""
        import asyncio
        import sys

        from protean.server.observatory.metrics import create_metrics_endpoint

        domain = _StatusDomain("import-fail-domain").build()

        # Remove the cached module so the lazy `from ... import` will re-execute
        saved = sys.modules.pop("protean.server.subscription_status", None)
        try:
            import builtins

            real_import = builtins.__import__

            def selective_import(name, *args, **kwargs):
                if "subscription_status" in name:
                    raise ImportError("simulated import failure")
                return real_import(name, *args, **kwargs)

            builtins.__import__ = selective_import
            try:
                endpoint_fn = create_metrics_endpoint([domain])
                response = asyncio.run(endpoint_fn())
            finally:
                builtins.__import__ = real_import

            assert response.status_code == 200
            # Subscription metrics should be absent (import failed)
            assert "protean_subscription_consumer_lag" not in response.body.decode()
        finally:
            # Restore the module so other tests aren't affected
            if saved is not None:
                sys.modules["protean.server.subscription_status"] = saved
