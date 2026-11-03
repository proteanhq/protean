"""Tests for ``exhausted_records``, the last-status-wins fold over a failed stream."""

from __future__ import annotations

from uuid import uuid4

from protean.server.subscription.event_store_subscription import FailedPositionStatus
from protean.utils.dlq import exhausted_records

FAILED_STREAM = "failed-app.Handler-order"


def _write(store, data: dict, record_type: str | None) -> None:
    headers = {"id": str(uuid4())}
    if record_type is not None:
        headers["type"] = record_type
    store._write(
        FAILED_STREAM,
        record_type or "Unknown",
        data,
        metadata={"headers": headers, "domain": {"kind": "read_position"}},
    )


def _record(store, position: int, status: FailedPositionStatus, **data) -> None:
    _write(store, {"position": position, **data}, status.value)


def test_latest_record_per_position_wins(test_domain):
    store = test_domain.event_store.store
    _record(store, 1, FailedPositionStatus.FAILED)
    _record(store, 2, FailedPositionStatus.FAILED)
    _record(store, 1, FailedPositionStatus.EXHAUSTED, marker="one")
    _record(store, 3, FailedPositionStatus.EXHAUSTED)
    _record(store, 2, FailedPositionStatus.EXHAUSTED, marker="two")
    _record(store, 3, FailedPositionStatus.RESOLVED)
    _record(store, 4, FailedPositionStatus.EXHAUSTED)
    _record(store, 4, FailedPositionStatus.PURGED)

    records = exhausted_records(store, FAILED_STREAM)

    assert sorted(records) == [1, 2]
    assert records[1].data["marker"] == "one"
    assert records[2].data["marker"] == "two"
    assert records[1].metadata.headers.type == FailedPositionStatus.EXHAUSTED.value


def test_records_without_position_or_type_are_skipped(test_domain):
    store = test_domain.event_store.store
    _record(store, 1, FailedPositionStatus.EXHAUSTED)
    # No position: cannot be attributed, so it is ignored.
    _write(store, {"retry_count": 3}, FailedPositionStatus.EXHAUSTED.value)
    # No header type: its status is unknown, so it does not override position 1.
    _write(store, {"position": 1}, None)

    records = exhausted_records(store, FAILED_STREAM)

    assert list(records) == [1]


def test_missing_stream_is_empty(test_domain):
    assert exhausted_records(test_domain.event_store.store, FAILED_STREAM) == {}
