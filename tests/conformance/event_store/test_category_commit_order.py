"""Rows of a category become visible in ``global_position`` order.

Eight writers append to their own streams of one category while a reader pages
the category by ``global_position``. A row that became visible before a row
with a lower ``global_position`` would let a reader page past the lower row,
and the reader would never see it. So every read taken during the writes must
be a prefix of the final read.
"""

import threading
import time

import pytest

from protean.port.event_store import EventStoreCapabilities

pytestmark = pytest.mark.requires(EventStoreCapabilities.CATEGORY_COMMIT_ORDER)

WRITERS = 8
WRITES_PER_WRITER = 25
TIMEOUT_SECONDS = 60
TOTAL = WRITERS * WRITES_PER_WRITER


def _write_stream(adapter, test_domain, barrier, member, errors) -> None:
    with test_domain.domain_context():
        try:
            barrier.wait()
            for n in range(WRITES_PER_WRITER):
                adapter.write_message(f"order-{member}", "Counted", {"n": n})
        except BaseException as exc:  # checked by the test
            errors.append(exc)


def _poll_category(adapter, test_domain, barrier, writers_done, reads, errors):
    deadline = time.monotonic() + TIMEOUT_SECONDS

    def read() -> None:
        rows = adapter.get_category_messages("order", limit=TOTAL * 2)
        reads.append([row["id"] for row in rows])

    with test_domain.domain_context():
        try:
            # One read before the writers start and one after they finish, so
            # ``reads`` is never empty when the writers finish before the
            # reader thread is scheduled.
            read()
            barrier.wait()
            while not writers_done.is_set() and time.monotonic() < deadline:
                read()
            read()
        except BaseException as exc:  # checked by the test
            errors.append(exc)


def test_every_read_during_the_writes_is_a_prefix_of_the_final_read(
    adapter, test_domain
):
    barrier = threading.Barrier(WRITERS + 1, timeout=30)
    writers_done = threading.Event()
    errors: list[BaseException] = []
    reads: list[list[str]] = []

    # Make the connection, or the pool, before the threads start, so they do
    # not race to create it.
    adapter.get_connection()

    writers = [
        threading.Thread(
            target=_write_stream, args=(adapter, test_domain, barrier, m, errors)
        )
        for m in range(WRITERS)
    ]
    polling = threading.Thread(
        target=_poll_category,
        args=(adapter, test_domain, barrier, writers_done, reads, errors),
    )
    polling.start()
    for thread in writers:
        thread.start()
    for thread in writers:
        thread.join(timeout=TIMEOUT_SECONDS)
    writers_done.set()
    polling.join(timeout=TIMEOUT_SECONDS)

    assert not any(thread.is_alive() for thread in [*writers, polling])
    assert errors == []

    final_rows = adapter.get_category_messages("order", limit=TOTAL * 2)
    final = [row["id"] for row in final_rows]
    assert len(final) == TOTAL
    positions = [row["global_position"] for row in final_rows]
    assert positions == sorted(set(positions))

    assert reads
    for read in reads:
        assert read == final[: len(read)]
