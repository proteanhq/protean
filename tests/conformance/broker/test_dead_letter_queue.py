"""Brokers that declare ``DEAD_LETTER_QUEUE`` list, replay and remove the
entries of a ``{stream}:dlq`` stream."""

from datetime import UTC, datetime, timedelta

import pytest

from protean.port.broker import BrokerCapabilities

pytestmark = pytest.mark.requires(BrokerCapabilities.DEAD_LETTER_QUEUE)

STREAM = "orders"
DLQ = "orders:dlq"
TARGET = "orders_replayed"
GROUP = "replay_group"


def dead_letter(broker, payload, *, stream=STREAM, original_id="o1"):
    """Put ``payload`` on ``{stream}:dlq`` with the metadata the engine writes
    for a failed message, and return its DLQ id."""
    return broker.publish(
        f"{stream}:dlq",
        {
            **payload,
            "_dlq_metadata": {
                "original_stream": stream,
                "original_id": original_id,
                "consumer_group": "group1",
                "failure_reason": "max_retries_exceeded",
                "failed_at": datetime.now(UTC).isoformat(),
                "retry_count": 3,
            },
        },
    )


def test_list_returns_the_entries_of_each_named_stream(broker):
    dead_letter(broker, {"data": "one"})
    dead_letter(broker, {"data": "two"}, stream="payments", original_id="p1")
    dead_letter(broker, {"data": "three"}, stream="refunds", original_id="r1")

    entries = broker.dlq_list([DLQ, "payments:dlq"])

    assert {entry.stream for entry in entries} == {"orders", "payments"}
    assert {entry.original_id for entry in entries} == {"o1", "p1"}


def test_list_returns_at_most_limit_entries(broker):
    for n in range(3):
        dead_letter(broker, {"n": n})

    assert len(broker.dlq_list([DLQ], limit=2)) == 2


def test_list_of_a_missing_stream_is_empty(broker):
    assert broker.dlq_list(["missing:dlq"]) == []


def test_get_returns_the_entry_and_its_metadata(broker):
    dlq_id = dead_letter(broker, {"data": "one"})

    entry = broker.dlq_get(DLQ, dlq_id)

    assert entry is not None
    assert entry.dlq_id == dlq_id
    assert entry.dlq_stream == DLQ
    assert entry.stream == STREAM
    assert entry.original_id == "o1"
    assert entry.consumer_group == "group1"
    assert entry.failure_reason == "max_retries_exceeded"
    assert entry.retry_count == 3
    assert entry.payload["data"] == "one"


def test_get_of_an_unknown_id_returns_none(broker):
    dead_letter(broker, {"data": "one"})

    assert broker.dlq_get(DLQ, "unknown") is None


def test_replay_publishes_the_entry_without_its_metadata_and_removes_it(broker):
    dlq_id = dead_letter(broker, {"data": "one"})
    kept = dead_letter(broker, {"data": "two"}, original_id="o2")

    assert broker.dlq_replay(DLQ, dlq_id, TARGET) is True

    assert broker.dlq_get(DLQ, dlq_id) is None
    assert broker.dlq_get(DLQ, kept) is not None
    _, message = broker.get_next(TARGET, GROUP)
    assert message == {"data": "one"}


def test_replay_of_an_unknown_id_returns_false(broker):
    dead_letter(broker, {"data": "one"})

    assert broker.dlq_replay(DLQ, "unknown", TARGET) is False
    assert broker.dlq_depth(DLQ) == 1


def test_replay_all_publishes_every_entry_and_empties_the_stream(broker):
    dead_letter(broker, {"n": 1})
    dead_letter(broker, {"n": 2}, original_id="o2")

    assert broker.dlq_replay_all(DLQ, TARGET) == 2

    assert broker.dlq_depth(DLQ) == 0
    replayed = broker.read(TARGET, GROUP, 5)
    assert sorted(message["n"] for _, message in replayed) == [1, 2]
    assert all("_dlq_metadata" not in message for _, message in replayed)


def test_purge_removes_every_entry_and_returns_the_count(broker):
    dead_letter(broker, {"n": 1})
    dead_letter(broker, {"n": 2}, original_id="o2")

    assert broker.dlq_purge(DLQ) == 2
    assert broker.dlq_depth(DLQ) == 0
    assert broker.dlq_list([DLQ]) == []


def test_depth_counts_the_entries_of_one_stream(broker):
    dead_letter(broker, {"n": 1})
    dead_letter(broker, {"n": 2}, original_id="o2")
    dead_letter(broker, {"n": 3}, stream="payments", original_id="p1")

    assert broker.dlq_depth(DLQ) == 2
    assert broker.dlq_depth("missing:dlq") == 0


def test_trim_removes_the_entries_that_failed_before_the_cutoff(broker):
    dead_letter(broker, {"n": 1})
    dead_letter(broker, {"n": 2}, original_id="o2")

    assert broker.dlq_trim(DLQ, datetime.now(UTC) + timedelta(days=1)) == 2
    assert broker.dlq_depth(DLQ) == 0


def test_trim_keeps_the_entries_that_failed_after_the_cutoff(broker):
    dead_letter(broker, {"n": 1})

    assert broker.dlq_trim(DLQ, datetime.now(UTC) - timedelta(days=1)) == 0
    assert broker.dlq_depth(DLQ) == 1


def test_trim_refuses_a_naive_cutoff(broker):
    dead_letter(broker, {"n": 1})

    with pytest.raises(ValueError, match="timezone-aware"):
        broker.dlq_trim(DLQ, datetime.now())
    assert broker.dlq_depth(DLQ) == 1
