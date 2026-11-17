"""``MemorySession.flush`` checks recorded versions, writes nothing, and holds
the provider lock until the session commits, rolls back or closes."""

import contextlib
import threading
from unittest.mock import patch

import pytest

from protean.adapters.database.memory import MemorySession
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ExpectedVersionError
from protean.fields import Identifier, Integer, String
from tests.shared import provider_adapter


class Counter(BaseAggregate):
    value: Integer(default=0)


class Renamed(BaseEvent):
    id: Identifier()
    name: String()


class User(BaseAggregate):
    name: String()

    def rename(self, name):
        self.name = name
        self.raise_(Renamed(id=self.id, name=name))


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Counter)
    test_domain.register(User)
    test_domain.register(Renamed, part_of=User)
    test_domain.init(traverse=False)


def _start_thread(test_domain, work):
    """Start ``work`` on its own thread and context, outside the open Unit of
    Work. Return the thread and the list its result lands in."""
    result = []

    def run():
        with test_domain.domain_context():
            result.append(work())

    thread = threading.Thread(target=run)
    thread.start()
    return thread, result


def _in_other_thread(test_domain, work):
    thread, result = _start_thread(test_domain, work)
    thread.join(timeout=10)
    assert result, "the thread did not finish"
    return result[0]


def _live_value(test_domain, identifier):
    return _in_other_thread(
        test_domain,
        lambda: test_domain.repository_for(Counter).get(identifier).value,
    )


def _set_value(test_domain, identifier, value):
    def work():
        counter = test_domain.repository_for(Counter).get(identifier)
        counter.value = value
        test_domain.repository_for(Counter).add(counter)
        return True

    return work


def _seed(test_domain):
    counter = Counter(value=0)
    test_domain.repository_for(Counter).add(counter)
    return counter.id


def test_flush_raises_when_another_writer_committed_first(test_domain):
    identifier = _seed(test_domain)
    repo = test_domain.repository_for(Counter)
    loser = repo.get(identifier)

    uow = UnitOfWork()
    uow.start()
    try:
        loser.value = 2
        repo.add(loser)
        _in_other_thread(test_domain, _set_value(test_domain, identifier, 1))
        with pytest.raises(ExpectedVersionError):
            uow._sessions["default"].flush()

        # The failed flush holds no lock: another thread still reads.
        assert _live_value(test_domain, identifier) == 1
    finally:
        uow.rollback()


def test_flush_of_a_current_write_passes_and_merges_nothing(test_domain):
    identifier = _seed(test_domain)
    repo = test_domain.repository_for(Counter)
    counter = repo.get(identifier)
    provider = provider_adapter(test_domain, "default")

    with UnitOfWork() as uow:
        counter.value = 3
        repo.add(counter)
        uow._sessions["default"].flush()
        schema = next(iter(provider._databases))
        assert provider._databases[schema][identifier]["value"] == 0

    assert _live_value(test_domain, identifier) == 3


def test_a_passed_flush_blocks_another_commit_until_this_commit(test_domain):
    identifier = _seed(test_domain)
    repo = test_domain.repository_for(Counter)
    counter = repo.get(identifier)

    with UnitOfWork() as uow:
        counter.value = 3
        repo.add(counter)
        uow._sessions["default"].flush()
        other, result = _start_thread(
            test_domain, _set_value(test_domain, identifier, 7)
        )
        other.join(timeout=0.5)
        assert other.is_alive()
        assert result == []

    other.join(timeout=10)
    assert result == [True]
    # The other writer ran after this commit, on the committed version.
    assert _live_value(test_domain, identifier) == 7


def test_rollback_after_a_passed_flush_releases_the_lock(test_domain):
    identifier = _seed(test_domain)
    repo = test_domain.repository_for(Counter)
    counter = repo.get(identifier)

    uow = UnitOfWork()
    uow.start()
    counter.value = 3
    repo.add(counter)
    uow._sessions["default"].flush()
    uow.rollback()

    assert _in_other_thread(test_domain, _set_value(test_domain, identifier, 5))
    assert _live_value(test_domain, identifier) == 5


def test_a_second_flush_keeps_one_hold(test_domain):
    identifier = _seed(test_domain)
    repo = test_domain.repository_for(Counter)
    counter = repo.get(identifier)

    with UnitOfWork() as uow:
        counter.value = 3
        repo.add(counter)
        uow._sessions["default"].flush()
        uow._sessions["default"].flush()

    # One commit released every hold the flushes took.
    assert _in_other_thread(test_domain, _set_value(test_domain, identifier, 4))


def test_a_failed_flush_after_a_passed_one_releases_the_lock(test_domain):
    current = _seed(test_domain)
    stale = _seed(test_domain)
    repo = test_domain.repository_for(Counter)
    counter = repo.get(current)
    loser = repo.get(stale)

    uow = UnitOfWork()
    uow.start()
    try:
        counter.value = 3
        repo.add(counter)
        # Commits after this session took its copy of the store.
        _in_other_thread(test_domain, _set_value(test_domain, stale, 1))
        uow._sessions["default"].flush()
        loser.value = 2
        repo.add(loser)
        with pytest.raises(ExpectedVersionError):
            uow._sessions["default"].flush()

        # The failed flush dropped the passed flush's hold too.
        assert _in_other_thread(test_domain, _set_value(test_domain, current, 8))
    finally:
        uow.rollback()


def test_close_after_a_passed_flush_releases_the_lock(test_domain):
    identifier = _seed(test_domain)
    session = provider_adapter(test_domain, "default").get_session()
    session.flush()
    session.close()

    assert _in_other_thread(test_domain, _set_value(test_domain, identifier, 6))


def test_no_commit_lands_between_the_flush_and_the_event_append(test_domain):
    """A commit on another thread cannot land between a Unit of Work's flush
    and its commit, so that commit cannot cause a version conflict after the
    Unit of Work's event is stored."""
    user = User(id="u1", name="a")
    test_domain.repository_for(User).add(user)
    identifier = _seed(test_domain)

    store = test_domain.event_store.store
    append = store.append
    others = []

    def append_while_another_writer_runs(event):
        others.append(
            _start_thread(test_domain, _set_value(test_domain, identifier, 9))
        )
        others[0][0].join(timeout=0.5)
        return append(event)

    store.append = append_while_another_writer_runs
    try:
        with UnitOfWork():
            loaded = test_domain.repository_for(User).get("u1")
            loaded.rename("b")
            test_domain.repository_for(User).add(loaded)
            counter = test_domain.repository_for(Counter).get(identifier)
            counter.value = 1
            test_domain.repository_for(Counter).add(counter)
    finally:
        store.append = append

    assert others, "the append ran no other writer"
    other, result = others[0]
    other.join(timeout=10)
    assert result == [True]

    assert test_domain.repository_for(User).get("u1").name == "b"
    assert [
        m["data"]["name"] for m in store.get_all_messages() if "name" in m["data"]
    ] == ["b"]
    assert _live_value(test_domain, identifier) == 9


def test_opposite_enlistment_orders_across_two_providers_do_not_deadlock(
    test_domain,
):
    """Two Units of Work that enlist two memory providers in opposite orders
    both commit, since each flushes the providers in the same order."""

    class Gauge(BaseAggregate):
        value: Integer(default=0)

    test_domain.config["databases"]["secondary"] = {"provider": "memory"}
    test_domain._initialize()
    test_domain.register(Gauge, database="secondary")
    test_domain.init(traverse=False)

    flush = MemorySession.flush
    flushed = threading.local()
    both_hold_one_lock = threading.Barrier(2)
    both_enlisted = threading.Barrier(2)

    def flush_then_wait_for_the_other_thread(session):
        flush(session)
        flushed.count = getattr(flushed, "count", 0) + 1
        if flushed.count == 1:
            # Without a fixed order each thread now holds one provider lock
            # and blocks on the other's. With it, the second thread is still
            # waiting for the first lock, so the barrier times out.
            with contextlib.suppress(threading.BrokenBarrierError):
                both_hold_one_lock.wait(timeout=0.5)

    committed = []

    def add_in_order(*aggregates):
        def run():
            with test_domain.domain_context(), UnitOfWork():
                for aggregate in aggregates:
                    test_domain.repository_for(type(aggregate)).add(aggregate)
                # A session snapshots its store under the provider lock, so
                # both threads enlist both providers before either flushes.
                both_enlisted.wait(timeout=10)
            committed.append(True)

        # A daemon thread, so a deadlock fails the test without hanging pytest.
        return threading.Thread(target=run, daemon=True)

    threads = [
        add_in_order(Counter(value=1), Gauge(value=1)),
        add_in_order(Gauge(value=2), Counter(value=2)),
    ]
    with patch.object(MemorySession, "flush", autospec=True) as patched:
        patched.side_effect = flush_then_wait_for_the_other_thread
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

    assert committed == [True, True]
