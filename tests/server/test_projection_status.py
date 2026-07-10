"""Tests for projection staleness monitoring (``projection_status``).

Exercises the collector against a real in-memory domain (registry walking, position
reading, lag/staleness aggregation, row counting) plus unit tests for the helpers.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.fields import Float, Identifier, String
from protean.server.projection_status import (
    ProjectionStatus,
    _aggregate,
    _feeder_statuses,
    _parse_time,
    _row_count,
    collect_projection_statuses,
)
from protean.server.subscription.profiles import SubscriptionType
from protean.server.subscription_status import (
    SubscriptionStatus,
    _extract_position_time,
)
from protean.utils import fqn

# ---------------------------------------------------------------------------
# Test elements
# ---------------------------------------------------------------------------


class User(BaseAggregate):
    email: String()
    name: String()


class Registered(BaseEvent):
    user_id: Identifier()
    email: String()
    name: String()


class Balances(BaseProjection):
    user_id: Identifier(identifier=True)
    name: String()
    balance: Float()


class BalancesProjector(BaseProjector):
    @on(Registered)
    def on_registered(self, event: Registered):
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Balances)
    test_domain.register(BalancesProjector, projector_for=Balances, aggregates=[User])
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Helpers to drive event-store state
# ---------------------------------------------------------------------------


def _stream_category() -> str:
    return BalancesProjector.meta_.stream_categories[0]


def _write_events(store, n: int) -> int:
    """Append ``n`` events to the projector's category; return the head position."""
    category = _stream_category()
    for i in range(n):
        # Events live in per-aggregate streams (``category-<id>``) that the
        # category head aggregates.
        store._write(f"{category}-{i}", "Registered", {"user_id": str(i)})
    return store.stream_head_position(category)


def _write_position(store, position: int, *, when: str | None = None) -> None:
    """Simulate the projector having processed up to ``position`` at time ``when``."""
    when = when or datetime.now(UTC).isoformat()
    position_stream = f"position-{fqn(BalancesProjector)}-{_stream_category()}"
    store._write(
        position_stream,
        "Read",
        {"position": position},
        metadata={"headers": {"time": when}},
    )


def _seed_rows(test_domain, n: int) -> None:
    repo = test_domain.repository_for(Balances)
    for i in range(n):
        repo.add(Balances(user_id=str(i), name=f"U{i}", balance=float(i)))


# ---------------------------------------------------------------------------
# collect_projection_statuses — real domain
# ---------------------------------------------------------------------------


class TestCollectProjectionStatuses:
    def test_lagging_projection_reports_staleness_lag_and_rows(self, test_domain):
        with test_domain.domain_context():
            store = test_domain.event_store.store
            head = _write_events(store, 5)
            _write_position(store, 2)  # processed up to 2, behind head
            _seed_rows(test_domain, 3)

            statuses = collect_projection_statuses(test_domain)

        by_name = {s.projection_name: s for s in statuses}
        assert "Balances" in by_name
        status = by_name["Balances"]
        assert status.lag == head - 2
        assert status.status == "lagging"
        # Position was just written, so staleness is a small non-negative number.
        assert status.staleness_seconds is not None
        assert status.staleness_seconds >= 0
        assert status.row_count == 3
        assert status.projectors == ["BalancesProjector"]
        assert status.last_updated is not None

    def test_caught_up_projection_is_ok_with_zero_staleness(self, test_domain):
        with test_domain.domain_context():
            store = test_domain.event_store.store
            head = _write_events(store, 4)
            _write_position(store, head)  # fully caught up

            statuses = collect_projection_statuses(test_domain)

        status = {s.projection_name: s for s in statuses}["Balances"]
        assert status.lag == 0
        assert status.status == "ok"
        assert status.staleness_seconds == 0.0

    def test_never_updated_projection_is_lagging_with_null_staleness(self, test_domain):
        """Events exist but the projector never wrote a position."""
        with test_domain.domain_context():
            store = test_domain.event_store.store
            _write_events(store, 3)  # no position written

            statuses = collect_projection_statuses(test_domain)

        status = {s.projection_name: s for s in statuses}["Balances"]
        assert status.lag is not None and status.lag > 0
        assert status.status == "lagging"
        assert status.last_updated is None
        assert status.staleness_seconds is None

    def test_no_events_is_unknown(self, test_domain):
        """No events at all → head is -1 → lag and staleness unknown."""
        with test_domain.domain_context():
            statuses = collect_projection_statuses(test_domain)

        status = {s.projection_name: s for s in statuses}["Balances"]
        assert status.lag is None
        assert status.status == "unknown"
        assert status.staleness_seconds is None

    def test_to_dict_roundtrips_all_fields(self, test_domain):
        with test_domain.domain_context():
            statuses = collect_projection_statuses(test_domain)
        d = statuses[0].to_dict()
        assert set(d) == {
            "projection_name",
            "projectors",
            "last_updated",
            "staleness_seconds",
            "lag",
            "row_count",
            "status",
        }

    def test_include_row_count_false_skips_count(self, test_domain):
        with test_domain.domain_context():
            statuses = collect_projection_statuses(test_domain, include_row_count=False)
        assert statuses
        assert all(s.row_count is None for s in statuses)


# ---------------------------------------------------------------------------
# _parse_time
# ---------------------------------------------------------------------------


class TestParseTime:
    def test_none_returns_none(self):
        assert _parse_time(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_time("") is None

    def test_aware_iso_preserved(self):
        result = _parse_time("2026-06-27T10:00:00+00:00")
        assert result is not None
        assert result.tzinfo is not None

    def test_naive_iso_assumed_utc(self):
        result = _parse_time("2026-06-27T10:00:00")
        assert result is not None
        assert result.tzinfo == UTC

    def test_garbage_returns_none(self):
        assert _parse_time("not-a-timestamp") is None

    def test_z_suffix_parsed_as_utc(self):
        result = _parse_time("2026-06-27T10:00:00Z")
        assert result is not None
        assert result.tzinfo == UTC


# ---------------------------------------------------------------------------
# _extract_position_time
# ---------------------------------------------------------------------------


class TestExtractPositionTime:
    def test_none_message(self):
        assert _extract_position_time(None) is None

    def test_top_level_time(self):
        assert _extract_position_time({"time": "2026-01-01T00:00:00Z"}) == (
            "2026-01-01T00:00:00Z"
        )

    def test_metadata_headers_time_dict(self):
        msg = {"metadata": {"headers": {"time": "2026-02-02T00:00:00Z"}}}
        assert _extract_position_time(msg) == "2026-02-02T00:00:00Z"

    def test_metadata_headers_time_json_string(self):
        msg = {"metadata": '{"headers": {"time": "2026-03-03T00:00:00Z"}}'}
        assert _extract_position_time(msg) == "2026-03-03T00:00:00Z"

    def test_missing_time_returns_none(self):
        assert _extract_position_time({"data": {"position": 1}}) is None

    def test_malformed_metadata_json_returns_none(self):
        assert _extract_position_time({"metadata": "{not json"}) is None

    def test_headers_as_json_string(self):
        msg = {"metadata": {"headers": '{"time": "2026-04-04T00:00:00Z"}'}}
        assert _extract_position_time(msg) == "2026-04-04T00:00:00Z"

    def test_malformed_headers_json_returns_none(self):
        assert _extract_position_time({"metadata": {"headers": "{bad"}}) is None

    def test_datetime_value_normalized_to_isoformat(self):
        dt = datetime(2026, 5, 5, 12, 0, 0, tzinfo=UTC)
        assert _extract_position_time({"time": dt}) == dt.isoformat()

    def test_metadata_datetime_value_normalized(self):
        dt = datetime(2026, 5, 5, 12, 0, 0, tzinfo=UTC)
        msg = {"metadata": {"headers": {"time": dt}}}
        assert _extract_position_time(msg) == dt.isoformat()


# ---------------------------------------------------------------------------
# _feeder_statuses / _row_count — branch coverage
# ---------------------------------------------------------------------------


class TestFeederStatuses:
    def test_skips_projector_for_other_projection(self):
        domain = MagicMock()
        other = MagicMock()
        other.meta_.projector_for = object()  # not Balances
        record = MagicMock()
        record.cls = other
        domain.registry.projectors = {"other": record}

        assert _feeder_statuses(domain, Balances, MagicMock()) == []

    def test_stream_type_projector_uses_stream_collector(self):
        domain = MagicMock()
        projector = MagicMock()
        projector.meta_.projector_for = Balances
        projector.meta_.stream_categories = ["user"]
        record = MagicMock()
        record.cls = projector
        domain.registry.projectors = {"p": record}

        resolver = MagicMock()
        resolver.resolve.return_value.subscription_type = SubscriptionType.STREAM

        stub = SubscriptionStatus(
            name="p-user",
            handler_name="P",
            subscription_type="stream",
            stream_category="user",
            lag=None,
            pending=0,
            current_position=None,
            head_position=None,
            status="unknown",
            consumer_count=0,
            dlq_depth=0,
        )
        with patch(
            "protean.server.projection_status._collect_stream_status",
            return_value=stub,
        ) as mock_stream:
            feeders = _feeder_statuses(domain, Balances, resolver)

        mock_stream.assert_called_once()
        assert len(feeders) == 1


class TestRowCount:
    def test_returns_none_on_error(self):
        domain = MagicMock()
        domain.repository_for.side_effect = RuntimeError("boom")
        assert _row_count(domain, Balances) is None


# ---------------------------------------------------------------------------
# _aggregate — pure aggregation with controlled "now"
# ---------------------------------------------------------------------------


_NOW = datetime(2026, 6, 27, 12, 0, 0, tzinfo=UTC)


def _feeder(lag, last_updated):
    return SubscriptionStatus(
        name="sub",
        handler_name="BalancesProjector",
        subscription_type="event_store",
        stream_category="user",
        lag=lag,
        pending=0,
        current_position=None,
        head_position=None,
        status="x",
        consumer_count=0,
        dlq_depth=0,
        last_updated=last_updated,
    )


class TestAggregate:
    def test_staleness_is_time_since_last_update_when_lagging(self):
        when = (_NOW - timedelta(seconds=90)).isoformat()
        result = _aggregate(
            Balances, [_feeder(5, when)], ["BalancesProjector"], _NOW, 0
        )
        assert result.lag == 5
        assert result.status == "lagging"
        assert result.staleness_seconds == 90.0

    def test_staleness_zero_when_caught_up(self):
        when = (_NOW - timedelta(seconds=90)).isoformat()
        result = _aggregate(
            Balances, [_feeder(0, when)], ["BalancesProjector"], _NOW, 0
        )
        assert result.status == "ok"
        assert result.staleness_seconds == 0.0

    def test_takes_worst_staleness_and_lag_across_feeders(self):
        recent = (_NOW - timedelta(seconds=30)).isoformat()
        old = (_NOW - timedelta(seconds=120)).isoformat()
        feeders = [_feeder(2, recent), _feeder(9, old)]
        result = _aggregate(Balances, feeders, ["BalancesProjector"], _NOW, 0)
        assert result.lag == 9
        assert result.staleness_seconds == 120.0

    def test_unknown_when_all_feeders_unknown(self):
        result = _aggregate(
            Balances, [_feeder(None, None)], ["BalancesProjector"], _NOW, 0
        )
        assert result.lag is None
        assert result.status == "unknown"
        assert result.staleness_seconds is None

    def test_never_updated_feeder_is_lagging_with_null_staleness(self):
        result = _aggregate(
            Balances, [_feeder(3, None)], ["BalancesProjector"], _NOW, 0
        )
        assert result.status == "lagging"
        assert result.staleness_seconds is None

    def test_future_timestamp_clamps_staleness_to_zero(self):
        # Clock skew: position timestamp ahead of "now" must not go negative.
        future = (_NOW + timedelta(seconds=30)).isoformat()
        result = _aggregate(
            Balances, [_feeder(5, future)], ["BalancesProjector"], _NOW, 0
        )
        assert result.staleness_seconds == 0.0

    def test_no_feeders_is_unknown(self):
        result = _aggregate(Balances, [], [], _NOW, None)
        assert result.lag is None
        assert result.status == "unknown"
        assert result.last_updated is None


def test_status_is_dataclass_instance(test_domain):
    with test_domain.domain_context():
        statuses = collect_projection_statuses(test_domain)
    assert all(isinstance(s, ProjectionStatus) for s in statuses)


# ---------------------------------------------------------------------------
# Staleness metric wiring (observatory/metrics)
# ---------------------------------------------------------------------------


class TestStalenessMetric:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        from protean.server.observatory.metrics import _scrape_cache

        _scrape_cache.clear()
        yield
        _scrape_cache.clear()

    def test_hand_rolled_metrics_includes_staleness(self, test_domain):
        from protean.server.observatory.metrics import _hand_rolled_metrics

        with test_domain.domain_context():
            store = test_domain.event_store.store
            head = _write_events(store, 4)
            _write_position(store, head)  # caught up -> staleness 0.0

        text = _hand_rolled_metrics([test_domain])
        assert "protean_projection_staleness_seconds" in text
        assert 'projection="Balances"' in text

    def test_metrics_collector_returns_domain_status_tuples(self, test_domain):
        from protean.server.observatory.metrics import _collect_projection_statuses

        with test_domain.domain_context():
            _write_events(test_domain.event_store.store, 3)

        collected = _collect_projection_statuses([test_domain])
        assert any(s.projection_name == "Balances" for _, s in collected)

    def test_collector_swallows_collection_errors(self, test_domain):
        from protean.server.observatory.metrics import _collect_projection_statuses

        with patch(
            "protean.server.projection_status.collect_projection_statuses",
            side_effect=RuntimeError("boom"),
        ):
            assert _collect_projection_statuses([test_domain]) == []

    def test_hand_rolled_skips_projection_without_staleness(self, test_domain):
        from protean.server.observatory.metrics import _hand_rolled_metrics

        # No events -> staleness is None -> data line skipped, HELP still emitted.
        text = _hand_rolled_metrics([test_domain])
        assert "# HELP protean_projection_staleness_seconds" in text
        assert "protean_projection_staleness_seconds{domain=" not in text

    def test_hand_rolled_handles_collection_error(self, test_domain):
        from protean.server.observatory import metrics as metrics_mod

        with patch.object(
            metrics_mod,
            "_collect_projection_statuses",
            side_effect=RuntimeError("boom"),
        ):
            text = metrics_mod._hand_rolled_metrics([test_domain])
        assert "protean_projection_staleness_seconds" not in text
