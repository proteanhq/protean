"""Tests for the Redis broker DLQ management API.

Backfills coverage for the DLQ methods (`dlq_list`, `dlq_inspect`, `dlq_replay`,
`dlq_replay_all`, `dlq_purge`, `dlq_trim`, `dlq_depth`), which had no Redis-side
tests. Mirrors the inline broker's ``test_dlq_management.py``.
"""

import pytest

from protean.adapters.broker.redis import RedisBroker
from tests.shared import REDIS_URI


def _broker(test_domain) -> RedisBroker:
    broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})
    broker._data_reset()  # clean slate for deterministic counts
    return broker


def _seed(
    broker: RedisBroker,
    dlq_stream: str,
    payload: dict,
    *,
    original_stream: str,
    original_id: str,
    consumer_group: str = "group1",
) -> str:
    """Publish a DLQ-formatted message and return its DLQ id."""
    message = {
        **payload,
        "_dlq_metadata": {
            "original_stream": original_stream,
            "original_id": original_id,
            "consumer_group": consumer_group,
            "failed_at": "2026-01-01T00:00:00+00:00",
            "retry_count": 3,
        },
    }
    return broker.publish(dlq_stream, message)


@pytest.mark.redis
class TestRedisDLQManagement:
    def test_dlq_list_returns_entries_across_streams(self, test_domain):
        broker = _broker(test_domain)
        _seed(
            broker,
            "orders:dlq",
            {"data": "one"},
            original_stream="orders",
            original_id="o1",
        )
        _seed(
            broker,
            "payments:dlq",
            {"data": "two"},
            original_stream="payments",
            original_id="p1",
        )

        entries = broker.dlq_list(["orders:dlq", "payments:dlq"])
        assert len(entries) == 2
        assert {e.stream for e in entries} == {"orders", "payments"}

    def test_dlq_list_empty_returns_empty(self, test_domain):
        broker = _broker(test_domain)
        assert broker.dlq_list(["nonexistent:dlq"]) == []

    def test_dlq_list_respects_limit(self, test_domain):
        broker = _broker(test_domain)
        for i in range(5):
            _seed(
                broker,
                "orders:dlq",
                {"i": i},
                original_stream="orders",
                original_id=f"o{i}",
            )
        assert len(broker.dlq_list(["orders:dlq"], limit=3)) == 3

    def test_dlq_inspect_found(self, test_domain):
        broker = _broker(test_domain)
        dlq_id = _seed(
            broker,
            "orders:dlq",
            {"key": "value"},
            original_stream="orders",
            original_id="o1",
            consumer_group="g1",
        )

        entry = broker.dlq_inspect("orders:dlq", dlq_id)
        assert entry is not None
        assert entry.dlq_id == dlq_id
        assert entry.original_id == "o1"
        assert entry.stream == "orders"
        assert entry.consumer_group == "g1"
        assert entry.payload["key"] == "value"

    def test_dlq_inspect_not_found(self, test_domain):
        broker = _broker(test_domain)
        _seed(
            broker, "orders:dlq", {"k": "v"}, original_stream="orders", original_id="o1"
        )
        assert broker.dlq_inspect("orders:dlq", "9999999999999-0") is None

    def test_dlq_replay_moves_message_to_target(self, test_domain):
        broker = _broker(test_domain)
        dlq_id = _seed(
            broker,
            "orders:dlq",
            {"amount": 10},
            original_stream="orders",
            original_id="o1",
        )

        assert broker.dlq_replay("orders:dlq", dlq_id, "orders") is True
        # Removed from the DLQ...
        assert broker.dlq_inspect("orders:dlq", dlq_id) is None
        # ...and republished (without DLQ metadata) to the target stream.
        messages = broker.read("orders", "replay-group", no_of_messages=10)
        assert len(messages) == 1
        _, replayed_payload = messages[0]
        assert replayed_payload["amount"] == 10
        assert "_dlq_metadata" not in replayed_payload

    def test_dlq_replay_all(self, test_domain):
        broker = _broker(test_domain)
        for i in range(3):
            _seed(
                broker,
                "orders:dlq",
                {"i": i},
                original_stream="orders",
                original_id=f"o{i}",
            )

        assert broker.dlq_replay_all("orders:dlq", "orders") == 3
        assert broker.dlq_depth("orders:dlq") == 0
        assert len(broker.read("orders", "replay-group", no_of_messages=10)) == 3

    def test_dlq_purge(self, test_domain):
        broker = _broker(test_domain)
        for i in range(2):
            _seed(
                broker,
                "orders:dlq",
                {"i": i},
                original_stream="orders",
                original_id=f"o{i}",
            )

        assert broker.dlq_purge("orders:dlq") == 2
        assert broker.dlq_depth("orders:dlq") == 0

    def test_dlq_purge_empty_stream(self, test_domain):
        broker = _broker(test_domain)
        assert broker.dlq_purge("nonexistent:dlq") == 0

    def test_dlq_depth(self, test_domain):
        broker = _broker(test_domain)
        assert broker.dlq_depth("orders:dlq") == 0
        for i in range(2):
            _seed(
                broker,
                "orders:dlq",
                {"i": i},
                original_stream="orders",
                original_id=f"o{i}",
            )
        assert broker.dlq_depth("orders:dlq") == 2

    def test_dlq_trim_removes_entries_below_cutoff(self, test_domain):
        broker = _broker(test_domain)
        for i in range(3):
            _seed(
                broker,
                "orders:dlq",
                {"i": i},
                original_stream="orders",
                original_id=f"o{i}",
            )
        assert broker.dlq_depth("orders:dlq") == 3

        # dlq_trim uses an approximate XTRIM MINID (whole-node trimming). A
        # far-future cutoff makes every entry eligible, so all are removed.
        assert broker.dlq_trim("orders:dlq", "9999999999999-0") == 3
        assert broker.dlq_depth("orders:dlq") == 0
