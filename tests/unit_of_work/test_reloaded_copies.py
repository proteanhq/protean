"""An aggregate read more than once in one UnitOfWork is one instance."""

import pytest

from protean.core.aggregate import BaseAggregate, apply
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


class Pinged(BaseEvent):
    marker_id: Identifier()


class Marker(BaseAggregate):
    name: String(max_length=50)

    def ping(self) -> None:
        self.raise_(Pinged(marker_id=self.id))


class Opened(BaseEvent):
    ledger_id: Identifier()


class Ledger(BaseAggregate):
    name: String(max_length=50)

    @apply
    def opened(self, event: Opened) -> None:
        self.id = event.ledger_id


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Tally)
    test_domain.register(Bumped, part_of=Tally)
    test_domain.register(Marker)
    test_domain.register(Pinged, part_of=Marker)
    test_domain.register(Ledger, event_sourced=True)
    test_domain.register(Opened, part_of=Ledger)
    test_domain.init(traverse=False)


@pytest.fixture
def tally(test_domain) -> Tally:
    tally = Tally(name="t")
    test_domain.repository_for(Tally).add(tally)
    return tally


def _bumped(test_domain, tally: Tally) -> list[tuple[int, int]]:
    messages = test_domain.event_store.store.read(
        f"{Tally.meta_.stream_category}-{tally.id}"
    )
    return [
        (message.metadata.event_store.position, message.data["value"])
        for message in messages
        if message.metadata.headers.type == Bumped.__type__
    ]


def test_a_second_get_returns_the_instance_already_tracked(test_domain, tally):
    repo = test_domain.repository_for(Tally)

    with UnitOfWork() as uow:
        first = repo.get(tally.id)
        second = repo.get(tally.id)
        found = repo._dao.query.filter(name="t").all().first

        assert second is first
        assert found is first
        tracked = [item for _, item in uow._tracked_items()]
        assert len(tracked) == 1
        assert tracked[0] is first


def test_events_from_a_save_and_a_later_read_both_commit(test_domain, tally):
    repo = test_domain.repository_for(Tally)

    with UnitOfWork():
        first = repo.get(tally.id)
        first.bump()
        repo.add(first)

        second = repo.get(tally.id)
        second.bump()
        repo.add(second)

    assert _bumped(test_domain, tally) == [(0, 1), (1, 2)]


def test_events_raised_before_a_reread_are_kept(test_domain, tally):
    repo = test_domain.repository_for(Tally)

    with UnitOfWork():
        first = repo.get(tally.id)
        first.bump()

        second = repo.get(tally.id)
        second.bump()
        repo.add(second)

    assert _bumped(test_domain, tally) == [(0, 1), (1, 2)]


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


def test_a_rollback_after_two_saves_restores_the_stored_version(test_domain, tally):
    repo = test_domain.repository_for(Tally)

    with pytest.raises(RuntimeError, match="abort"), UnitOfWork():
        first = repo.get(tally.id)
        first.value += 1
        repo.add(first)

        second = repo.get(tally.id)
        second.value += 1
        repo.add(second)
        raise RuntimeError("abort")

    assert second._version == 0
    assert second._next_version == 1

    second.value += 1
    repo.add(second)
    assert repo.get(tally.id)._version == 1


def test_aggregates_of_two_types_with_one_id_are_tracked_apart(test_domain):
    test_domain.repository_for(Tally).add(Tally(id="shared", name="t"))
    test_domain.repository_for(Marker).add(Marker(id="shared", name="m"))

    with UnitOfWork():
        tally = test_domain.repository_for(Tally).get("shared")
        marker = test_domain.repository_for(Marker).get("shared")
        tally.bump()
        marker.ping()
        test_domain.repository_for(Tally).add(tally)
        test_domain.repository_for(Marker).add(marker)

    store = test_domain.event_store.store
    assert len(store.read(f"{Tally.meta_.stream_category}-shared")) == 1
    assert len(store.read(f"{Marker.meta_.stream_category}-shared")) == 1


def test_an_event_sourced_get_returns_the_instance_already_tracked(test_domain):
    repo = test_domain.repository_for(Ledger)
    ledger = Ledger(name="l")
    ledger.raise_(Opened(ledger_id=ledger.id))
    repo.add(ledger)

    with UnitOfWork():
        first = repo.get(ledger.id)
        second = repo.get(ledger.id)

        assert second is first
