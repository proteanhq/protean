"""An aggregate read more than once in one UnitOfWork."""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ExpectedVersionError
from protean.fields import Identifier, Integer, String


class Bumped(BaseEvent):
    tally_id: Identifier()
    value: Integer()


class Tally(BaseAggregate):
    name: String(max_length=50)
    value: Integer(default=0)

    def bump(self) -> None:
        self.value += 1
        self.raise_(Bumped(tally_id=self.id, value=self.value))


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Tally)
    test_domain.register(Bumped, part_of=Tally)
    test_domain.init(traverse=False)


@pytest.fixture
def tally(test_domain) -> Tally:
    tally = Tally(name="t")
    test_domain.repository_for(Tally).add(tally)
    return tally


def _bumped_values(test_domain, tally: Tally) -> list[tuple[int, int]]:
    messages = test_domain.event_store.store.read(
        f"{Tally.meta_.stream_category}-{tally.id}"
    )
    return [
        (message.metadata.event_store.position, message.data["value"])
        for message in messages
        if message.metadata.headers.type == Bumped.__type__
    ]


def test_events_from_a_saved_copy_and_its_reload_both_commit(test_domain, tally):
    repo = test_domain.repository_for(Tally)

    with UnitOfWork():
        first = repo.get(tally.id)
        first.bump()
        repo.add(first)

        second = repo.get(tally.id)
        second.bump()
        repo.add(second)

    assert _bumped_values(test_domain, tally) == [(0, 1), (1, 2)]


def test_a_write_by_another_transaction_still_conflicts(test_domain, tally):
    repo = test_domain.repository_for(Tally)
    concurrent = repo.get(tally.id)
    concurrent.bump()

    with pytest.raises(ExpectedVersionError), UnitOfWork():
        first = repo.get(tally.id)
        first.bump()
        repo.add(first)

        test_domain.event_store.store.append(concurrent._events[0])

        second = repo.get(tally.id)
        second.bump()
        repo.add(second)


def test_read_copies_are_not_retained(test_domain, tally):
    repo = test_domain.repository_for(Tally)

    with UnitOfWork() as uow:
        copies = [repo.get(tally.id) for _ in range(5)]

        tracked = [item for _, item in uow._tracked_items()]
        assert len(tracked) == 1
        assert tracked[0] is copies[-1]


def test_a_saved_copy_stays_tracked_after_a_reload(test_domain, tally):
    repo = test_domain.repository_for(Tally)

    with UnitOfWork() as uow:
        saved = repo.get(tally.id)
        saved.value += 1
        repo.add(saved)
        reloaded = repo.get(tally.id)

        tracked = [item for _, item in uow._tracked_items()]
        assert len(tracked) == 2
        assert tracked[0] is saved
        assert tracked[1] is reloaded
