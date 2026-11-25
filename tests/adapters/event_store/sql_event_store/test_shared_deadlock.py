"""Two Unit of Work commits that lock the same categories in opposite orders
both commit on PostgreSQL, because each commit takes its locks in key order."""

import threading
import time

import pytest

from protean import Domain
from protean.core.unit_of_work import UnitOfWork


@pytest.mark.postgresql
@pytest.mark.no_test_domain
class TestCommitsTakeCategoryLocksInKeyOrder:
    @pytest.fixture
    def backend(self) -> str:
        return "postgresql"

    def test_opposite_orders_both_commit(self, make_shared_domain):
        domain: Domain = make_shared_domain()
        store = domain.event_store._require_adapter()
        # Both commits reach their locks together. The pause after each lock
        # gives the other commit time to take its first lock, so an unsorted
        # order deadlocks every time.
        barrier = threading.Barrier(2, timeout=10)
        store._on_commit_callback_entered = barrier.wait
        store._on_lock_taken = lambda: time.sleep(0.3)
        errors: list[BaseException] = []

        def commit(first: str, second: str) -> None:
            try:
                with domain.domain_context():
                    with UnitOfWork():
                        store.write_message(f"{first}-1", "Written", {})
                        store.write_message(f"{second}-1", "Written", {})
            except BaseException as exc:  # reported by the assertion below
                errors.append(exc)

        threads = [
            threading.Thread(target=commit, args=("a", "b")),
            threading.Thread(target=commit, args=("b", "a")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert not any(thread.is_alive() for thread in threads)
        assert errors == []
        rows = store.get_all_messages()
        assert sorted(row["stream_name"] for row in rows) == [
            "a-1",
            "a-1",
            "b-1",
            "b-1",
        ]
