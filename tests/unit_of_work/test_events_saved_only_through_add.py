"""A Unit of Work saves an aggregate's events only once ``add()`` has saved it.

A read alone tracks the aggregate, but what is raised on it is discarded at
commit, for state-based and event-sourced aggregates alike.
"""

import logging

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.domain import Domain
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
    name: String(max_length=50)


class Renamed(BaseEvent):
    ledger_id: Identifier()
    name: String(max_length=50)


class Ledger(BaseAggregate):
    name: String(max_length=50)

    @classmethod
    def open(cls, name: str) -> "Ledger":
        ledger = cls(name=name)
        ledger.raise_(Opened(ledger_id=ledger.id, name=name))
        return ledger

    def rename(self, name: str) -> None:
        self.raise_(Renamed(ledger_id=self.id, name=name))

    @apply
    def opened(self, event: Opened) -> None:
        self.id = event.ledger_id
        self.name = event.name

    @apply
    def renamed(self, event: Renamed) -> None:
        self.name = event.name


@pytest.fixture
def test_domain():
    """An outbox-enabled domain, so a test can check the outbox too."""
    domain = Domain(name="Test")
    domain.config["enable_outbox"] = True
    domain.config["server"]["default_subscription_type"] = "stream"

    with domain.domain_context():
        yield domain


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Tally)
    test_domain.register(Bumped, part_of=Tally)
    test_domain.register(Marker)
    test_domain.register(Pinged, part_of=Marker)
    test_domain.register(Ledger, is_event_sourced=True)
    test_domain.register(Opened, part_of=Ledger)
    test_domain.register(Renamed, part_of=Ledger)
    test_domain.init(traverse=False)


@pytest.fixture
def tally(test_domain) -> Tally:
    tally = Tally(name="t")
    test_domain.repository_for(Tally).add(tally)
    return tally


@pytest.fixture
def ledger(test_domain) -> Ledger:
    ledger = Ledger.open("first")
    test_domain.repository_for(Ledger).add(ledger)
    return ledger


def _stored_types(test_domain, aggregate: BaseAggregate) -> list[str]:
    stream = f"{type(aggregate).meta_.stream_category}-{aggregate.id}"
    return [
        message.metadata.headers.type
        for message in test_domain.event_store.store.read(stream)
    ]


def _outbox_types(test_domain) -> list[str]:
    rows = test_domain._get_outbox_repo("default").find_unprocessed()
    return sorted(row.type for row in rows)


def test_a_read_and_raise_without_add_saves_no_event(test_domain, tally, caplog):
    stored_before = _stored_types(test_domain, tally)
    outbox_before = _outbox_types(test_domain)

    with caplog.at_level(logging.DEBUG, logger="protean.core.unit_of_work"):
        with UnitOfWork():
            found = test_domain.repository_for(Tally).get(tally.id)
            found.bump()

    assert Bumped.__type__ not in _stored_types(test_domain, tally)
    assert _stored_types(test_domain, tally) == stored_before
    assert _outbox_types(test_domain) == outbox_before
    assert test_domain.repository_for(Tally).get(tally.id).value == 0
    assert [
        record
        for record in caplog.records
        if record.name == "protean.core.unit_of_work"
        and record.levelno >= logging.WARNING
    ] == []


def test_a_read_and_raise_with_add_saves_the_event_and_the_state(test_domain, tally):
    outbox_before = _outbox_types(test_domain)

    with UnitOfWork():
        repo = test_domain.repository_for(Tally)
        found = repo.get(tally.id)
        found.bump()
        repo.add(found)

    assert _stored_types(test_domain, tally).count(Bumped.__type__) == 1
    assert _outbox_types(test_domain) == sorted([*outbox_before, Bumped.__type__])
    assert test_domain.repository_for(Tally).get(tally.id).value == 1


def test_a_read_alone_saves_nothing(test_domain, tally):
    stored_before = _stored_types(test_domain, tally)
    outbox_before = _outbox_types(test_domain)

    with UnitOfWork():
        test_domain.repository_for(Tally).get(tally.id)

    assert _stored_types(test_domain, tally) == stored_before
    assert _outbox_types(test_domain) == outbox_before
    reloaded = test_domain.repository_for(Tally).get(tally.id)
    assert (reloaded.name, reloaded.value) == ("t", 0)


def test_events_raised_after_add_in_the_same_transaction_are_saved(test_domain, tally):
    with UnitOfWork():
        repo = test_domain.repository_for(Tally)
        found = repo.get(tally.id)
        found.bump()
        repo.add(found)
        found.bump()

    assert _stored_types(test_domain, tally).count(Bumped.__type__) == 2


def test_only_the_added_aggregate_commits_its_events(test_domain, tally, caplog):
    marker = Marker(name="m")
    test_domain.repository_for(Marker).add(marker)

    with caplog.at_level(logging.WARNING, logger="protean.core.unit_of_work"):
        with UnitOfWork():
            found_marker = test_domain.repository_for(Marker).get(marker.id)
            found_marker.ping()

            repo = test_domain.repository_for(Tally)
            found = repo.get(tally.id)
            found.bump()
            repo.add(found)

    assert _stored_types(test_domain, tally).count(Bumped.__type__) == 1
    assert Pinged.__type__ not in _stored_types(test_domain, marker)
    assert not any(
        "Multiple aggregate types" in record.getMessage() for record in caplog.records
    )


def test_an_add_inside_a_nested_unit_of_work_counts_at_the_outer_commit(
    test_domain, tally
):
    repo = test_domain.repository_for(Tally)

    with UnitOfWork():
        found = repo.get(tally.id)
        found.bump()
        with UnitOfWork():
            repo.add(found)

    assert _stored_types(test_domain, tally).count(Bumped.__type__) == 1
    assert repo.get(tally.id).value == 1


def test_an_event_sourced_read_and_raise_without_add_saves_no_event(
    test_domain, ledger
):
    with UnitOfWork():
        found = test_domain.repository_for(Ledger).get(ledger.id)
        found.rename("second")

    assert _stored_types(test_domain, ledger) == [Opened.__type__]
    assert test_domain.repository_for(Ledger).get(ledger.id).name == "first"


def test_an_event_sourced_read_and_raise_with_add_saves_the_event(test_domain, ledger):
    with UnitOfWork():
        repo = test_domain.repository_for(Ledger)
        found = repo.get(ledger.id)
        found.rename("second")
        repo.add(found)

    assert _stored_types(test_domain, ledger) == [Opened.__type__, Renamed.__type__]
    assert test_domain.repository_for(Ledger).get(ledger.id).name == "second"
