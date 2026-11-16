"""Category reads: exact category match, paged by ``global_position`` inclusive
(ADR-0024).

A category read returns the streams ``<category>-<id>`` and the stream named
``<category>``. It leaves out a longer category that ends with the same text,
such as ``poweruser`` for ``user``, and the snapshot streams
``<category>:snapshot-<id>``.
"""

import pytest

from protean.port.event_store import EventStoreCapabilities

pytestmark = pytest.mark.requires(EventStoreCapabilities.READ_CATEGORY)


def _write(adapter, stream_name: str, n: int) -> None:
    adapter.write_message(stream_name, "Counted", {"n": n})


def _streams(rows) -> list[str]:
    return [row["stream_name"] for row in rows]


def _numbers(rows) -> list[int]:
    return [row["data"]["n"] for row in rows]


def _write_exact_match_streams(adapter, prefix: str = "") -> None:
    # Each stream has its own id, so a read that matched ``poweruser-2`` or
    # ``user:snapshot-3`` would show their ids.
    _write(adapter, f"{prefix}user-1", 0)
    _write(adapter, f"{prefix}poweruser-2", 1)
    adapter.write_message(f"{prefix}user:snapshot-3", "SNAPSHOT", {"_version": 0})
    _write(adapter, f"{prefix}user-1", 2)


@pytest.mark.parametrize("prefix", ["", "test::"], ids=["plain", "prefixed"])
def test_returns_only_the_streams_of_the_exact_category(adapter, prefix):
    _write_exact_match_streams(adapter, prefix)

    rows = adapter.get_category_messages(f"{prefix}user")

    assert _streams(rows) == [f"{prefix}user-1", f"{prefix}user-1"]
    assert _numbers(rows) == [0, 2]


def test_a_read_of_the_longer_category_returns_only_its_streams(adapter):
    _write_exact_match_streams(adapter)

    assert _streams(adapter.get_category_messages("poweruser")) == ["poweruser-2"]


def test_includes_the_stream_named_as_the_category(adapter):
    _write(adapter, "user", 0)
    _write(adapter, "users-1", 1)
    _write(adapter, "user-2", 2)

    assert _streams(adapter.get_category_messages("user")) == ["user", "user-2"]


def test_an_empty_category_returns_no_rows(adapter):
    _write(adapter, "order-1", 0)

    assert adapter.get_category_messages("user") == []


def test_orders_the_streams_of_a_category_by_global_position(adapter):
    # Three rows on one stream, then one on a second: in stream-position order
    # the second stream's row would come second.
    for n in range(3):
        _write(adapter, "user-1", n)
    _write(adapter, "user-2", 3)

    rows = adapter.get_category_messages("user")

    positions = [row["global_position"] for row in rows]
    assert positions == sorted(positions)
    assert len(set(positions)) == 4
    assert _numbers(rows) == [0, 1, 2, 3]


def test_reads_from_the_given_global_position_inclusive(adapter):
    for n in range(3):
        _write(adapter, "user-1", n)
    _write(adapter, "user-2", 3)
    rows = adapter.get_category_messages("user")
    assert len(rows) == 4

    # No stream has a stream position as high as the third row's global
    # position, so a read keyed on stream position returns nothing here.
    page = adapter.get_category_messages("user", position=rows[2]["global_position"])

    assert [row["id"] for row in page] == [row["id"] for row in rows[2:]]


def test_pages_past_rows_of_other_categories(adapter):
    _write(adapter, "user-1", 0)
    _write(adapter, "other-1", 1)
    _write(adapter, "user-2", 2)
    _write(adapter, "user-1", 3)
    rows = adapter.get_category_messages("user")
    assert _numbers(rows) == [0, 2, 3]

    page = adapter.get_category_messages(
        "user", position=rows[1]["global_position"], limit=1
    )

    assert _numbers(page) == [2]


def test_returns_at_most_limit_rows(adapter):
    for n in range(5):
        _write(adapter, f"user-{n}", n)

    assert _numbers(adapter.get_category_messages("user", limit=3)) == [0, 1, 2]


def test_a_position_past_the_last_row_returns_no_rows(adapter):
    _write(adapter, "user-1", 0)
    last = adapter.get_category_messages("user")[-1]

    assert (
        adapter.get_category_messages("user", position=last["global_position"] + 1)
        == []
    )
