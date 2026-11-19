"""Tests for the Redis broker DLQ management API.

Backfills coverage for the DLQ methods (`dlq_list`, `dlq_get`, `dlq_replay`,
`dlq_replay_all`, `dlq_purge`, `dlq_trim`, `dlq_depth`), which had no Redis-side
tests. Covers the core DLQ operations also tested in the inline broker's
``test_dlq_management.py``, though not all edge cases are replicated here.
"""

import time
from datetime import UTC, datetime, timedelta, timezone

import pytest
import redis

from protean.adapters.broker.redis import RedisBroker, _is_stream_id
from tests.shared import REDIS_URI


def _broker(test_domain) -> RedisBroker:
    broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})
    broker.clear()
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


def _at_millisecond_of(dlq_id: str) -> datetime:
    """Return the aware time of the millisecond a stream ID starts with."""
    milliseconds = int(dlq_id.split("-")[0])
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=milliseconds)


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

    def test_dlq_list_raises_for_a_key_that_is_not_a_stream(self, test_domain):
        broker = _broker(test_domain)
        broker._client.set("orders:dlq", "not-a-stream")
        with pytest.raises(redis.ResponseError, match="WRONGTYPE"):
            broker.dlq_list(["orders:dlq"])

    def test_dlq_list_filters_by_stream(self, test_domain):
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

        entries = broker.dlq_list(["orders:dlq"])
        assert len(entries) == 1
        assert entries[0].stream == "orders"

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

    def test_dlq_get_found(self, test_domain):
        broker = _broker(test_domain)
        dlq_id = _seed(
            broker,
            "orders:dlq",
            {"key": "value"},
            original_stream="orders",
            original_id="o1",
            consumer_group="g1",
        )

        entry = broker.dlq_get("orders:dlq", dlq_id)
        assert entry is not None
        assert entry.dlq_id == dlq_id
        assert entry.original_id == "o1"
        assert entry.stream == "orders"
        assert entry.consumer_group == "g1"
        assert entry.payload["key"] == "value"

    def test_dlq_get_not_found(self, test_domain):
        broker = _broker(test_domain)
        _seed(
            broker, "orders:dlq", {"k": "v"}, original_stream="orders", original_id="o1"
        )
        assert broker.dlq_get("orders:dlq", "9999999999999-0") is None

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
        assert broker.dlq_get("orders:dlq", dlq_id) is None
        # ...and republished (without DLQ metadata) to the target stream.
        messages = broker.read("orders", "replay-group", limit=10)
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
        assert len(broker.read("orders", "replay-group", limit=10)) == 3

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

        cutoff = datetime.now(UTC) + timedelta(hours=1)
        assert broker.dlq_trim("orders:dlq", cutoff) == 3
        assert broker.dlq_depth("orders:dlq") == 0

    def test_dlq_trim_removes_only_the_entry_before_the_cutoff(self, test_domain):
        broker = _broker(test_domain)
        _seed(
            broker, "orders:dlq", {"i": 0}, original_stream="orders", original_id="o0"
        )
        time.sleep(0.005)  # The second entry gets a later millisecond.
        newer_id = _seed(
            broker, "orders:dlq", {"i": 1}, original_stream="orders", original_id="o1"
        )

        assert broker.dlq_trim("orders:dlq", _at_millisecond_of(newer_id)) == 1

        [entry] = broker.dlq_list(["orders:dlq"])
        assert entry.dlq_id == newer_id

    def test_an_entry_added_in_the_cutoff_millisecond_is_kept(self, test_domain):
        broker = _broker(test_domain)
        dlq_id = _seed(
            broker, "orders:dlq", {"i": 0}, original_stream="orders", original_id="o0"
        )
        cutoff = _at_millisecond_of(dlq_id)

        assert broker.dlq_trim("orders:dlq", cutoff + timedelta(microseconds=999)) == 0
        assert broker.dlq_trim("orders:dlq", cutoff + timedelta(milliseconds=1)) == 1

    def test_dlq_trim_compares_the_instant_in_any_time_zone(self, test_domain):
        broker = _broker(test_domain)
        dlq_id = _seed(
            broker, "orders:dlq", {"i": 0}, original_stream="orders", original_id="o0"
        )
        later = _at_millisecond_of(dlq_id) + timedelta(milliseconds=1)
        elsewhere = later.astimezone(timezone(timedelta(hours=-5)))

        assert broker.dlq_trim("orders:dlq", elsewhere) == 1

    def test_dlq_trim_rejects_a_naive_cutoff(self, test_domain):
        broker = _broker(test_domain)

        with pytest.raises(ValueError, match="timezone-aware"):
            broker.dlq_trim("orders:dlq", datetime(2026, 1, 1))

    def test_dlq_get_finds_an_entry_by_its_millisecond_id(self, test_domain):
        broker = _broker(test_domain)
        dlq_id = _seed(
            broker, "orders:dlq", {"k": "v"}, original_stream="orders", original_id="o1"
        )
        millisecond_id = dlq_id.split("-")[0]

        entry = broker.dlq_get("orders:dlq", millisecond_id)
        assert entry is not None
        assert entry.dlq_id == dlq_id

    def test_dlq_replay_of_a_missing_stream_returns_false(self, test_domain):
        broker = _broker(test_domain)
        assert broker.dlq_replay("nonexistent:dlq", "1-0", "orders") is False

    def test_dlq_replay_all_of_a_missing_stream_returns_zero(self, test_domain):
        broker = _broker(test_domain)
        assert broker.dlq_replay_all("nonexistent:dlq", "orders") == 0


# Range bounds, non-ASCII digits, parts above 2**64 - 1 and IDs longer than 127
# characters (including ones too long for ``int()``), all of which XRANGE would
# treat as a range or reject.
MALFORMED_IDS = [
    "abc",
    "1-",
    "-",
    "+",
    "(1-0",
    "1-0\n",
    "",
    "\u0661\u0662\u0663",
    "\uff11",
    "1-\uff10",
    "18446744073709551616",
    "1-18446744073709551616",
    pytest.param("9" * 5000, id="5000-digits"),
    pytest.param("0" * 5000 + "1-0", id="5000-zero-padded"),
    pytest.param("0" * 127 + "1", id="128-chars"),
]


@pytest.mark.parametrize(
    "dlq_id",
    [
        "0",
        "0-0",
        "1-0",
        "18446744073709551615-18446744073709551615",
        pytest.param("0" * 126 + "1", id="127-chars"),
    ],
)
def test_is_stream_id_accepts_a_valid_id(dlq_id):
    assert _is_stream_id(dlq_id) is True


@pytest.mark.parametrize("dlq_id", MALFORMED_IDS)
def test_is_stream_id_rejects_a_malformed_id(dlq_id):
    assert _is_stream_id(dlq_id) is False


@pytest.mark.redis
class TestRedisDLQErrors:
    """A DLQ key that is not a stream raises instead of reading as empty."""

    @pytest.fixture
    def broker(self, test_domain) -> RedisBroker:
        broker = _broker(test_domain)
        broker._client.set("orders:dlq", "not-a-stream")
        return broker

    def test_dlq_get_raises(self, broker):
        with pytest.raises(redis.ResponseError, match="WRONGTYPE"):
            broker.dlq_get("orders:dlq", "1-0")

    def test_dlq_replay_raises(self, broker):
        with pytest.raises(redis.ResponseError, match="WRONGTYPE"):
            broker.dlq_replay("orders:dlq", "1-0", "orders")

    def test_dlq_replay_all_raises(self, broker):
        with pytest.raises(redis.ResponseError, match="WRONGTYPE"):
            broker.dlq_replay_all("orders:dlq", "orders")

    def test_dlq_purge_raises_and_keeps_the_key(self, broker):
        with pytest.raises(redis.ResponseError, match="WRONGTYPE"):
            broker.dlq_purge("orders:dlq")
        assert broker._client.get("orders:dlq") == b"not-a-stream"

    def test_dlq_depth_raises(self, broker):
        with pytest.raises(redis.ResponseError, match="WRONGTYPE"):
            broker.dlq_depth("orders:dlq")

    # The key is not a stream, so any call that reached Redis would raise
    # WRONGTYPE. A plain return proves the ID check ran first.
    @pytest.mark.parametrize("bad_id", MALFORMED_IDS)
    def test_dlq_get_of_a_malformed_id_returns_none(self, broker, bad_id):
        assert broker.dlq_get("orders:dlq", bad_id) is None

    @pytest.mark.parametrize("bad_id", MALFORMED_IDS)
    def test_dlq_replay_of_a_malformed_id_returns_false(self, broker, bad_id):
        assert broker.dlq_replay("orders:dlq", bad_id, "orders") is False

    @pytest.mark.parametrize(
        "max_id",
        [
            "18446744073709551615",
            "18446744073709551615-18446744073709551615",
            "0018446744073709551615",
        ],
    )
    def test_an_id_at_the_64_bit_limit_reaches_redis(self, broker, max_id):
        with pytest.raises(redis.ResponseError, match="WRONGTYPE"):
            broker.dlq_get("orders:dlq", max_id)
