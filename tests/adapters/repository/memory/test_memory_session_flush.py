"""``MemorySession.flush`` checks recorded versions and writes nothing."""

import threading

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ExpectedVersionError
from protean.fields import Integer


class Counter(BaseAggregate):
    value: Integer(default=0)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Counter)
    test_domain.init(traverse=False)


def _in_other_thread(test_domain, work):
    """Run ``work`` on its own thread and context, outside the open Unit of
    Work, and return its result."""
    result = []

    def run():
        with test_domain.domain_context():
            result.append(work())

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout=10)
    assert result, "the thread did not finish"
    return result[0]


def _live_value(test_domain, identifier):
    return _in_other_thread(
        test_domain,
        lambda: test_domain.repository_for(Counter).get(identifier).value,
    )


def _seed(test_domain):
    counter = Counter(value=0)
    test_domain.repository_for(Counter).add(counter)
    return counter.id


def test_flush_raises_when_another_writer_committed_first(test_domain):
    identifier = _seed(test_domain)
    repo = test_domain.repository_for(Counter)
    loser = repo.get(identifier)

    def commit_winner():
        winner = test_domain.repository_for(Counter).get(identifier)
        winner.value = 1
        test_domain.repository_for(Counter).add(winner)
        return True

    uow = UnitOfWork()
    uow.start()
    try:
        loser.value = 2
        repo.add(loser)
        _in_other_thread(test_domain, commit_winner)
        with pytest.raises(ExpectedVersionError):
            uow._sessions["default"].flush()
    finally:
        uow.rollback()

    assert _live_value(test_domain, identifier) == 1


def test_flush_of_a_current_write_passes_and_merges_nothing(test_domain):
    identifier = _seed(test_domain)
    repo = test_domain.repository_for(Counter)
    counter = repo.get(identifier)

    with UnitOfWork() as uow:
        counter.value = 3
        repo.add(counter)
        uow._sessions["default"].flush()
        assert _live_value(test_domain, identifier) == 0

    assert _live_value(test_domain, identifier) == 3
