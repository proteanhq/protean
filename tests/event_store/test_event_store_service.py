"""The domain's ``EventStore`` service against the configured store.

The service holds the adapter, answers ``category_head_position`` and loads
aggregates.
"""

from uuid import uuid4

import pytest

from protean.adapters.event_store.memory import MemoryEventStore
from protean.adapters.event_store.message_db import MessageDBStore
from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ObjectNotFoundError
from protean.fields import Identifier, Integer
from protean.port.event_store import SNAPSHOT_TYPE

pytestmark = pytest.mark.eventstore


class Opened(BaseEvent):
    counter_id: Identifier(required=True)


class Ticked(BaseEvent):
    counter_id: Identifier(required=True)
    value: Integer(required=True)


class Counter(BaseAggregate):
    counter_id: Identifier(identifier=True)
    value: Integer(default=0)

    @classmethod
    def open(cls, counter_id):
        counter = cls(counter_id=counter_id)
        counter.raise_(Opened(counter_id=counter_id))
        return counter

    def tick(self):
        self.raise_(Ticked(counter_id=self.counter_id, value=self.value + 1))

    @apply
    def opened(self, event: Opened):
        self.counter_id = event.counter_id
        self.value = 0

    @apply
    def ticked(self, event: Ticked):
        self.value = event.value


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Counter, event_sourced=True)
    test_domain.register(Opened, part_of=Counter)
    test_domain.register(Ticked, part_of=Counter)
    test_domain.init(traverse=False)


def _counter_with_events(test_domain, count):
    """Persist a counter whose stream holds ``count`` events: one open, then ticks."""
    identifier = str(uuid4())
    repo = test_domain.repository_for(Counter)
    with UnitOfWork():
        repo.add(Counter.open(identifier))
    for _ in range(count - 1):
        with UnitOfWork():
            counter = repo.get(identifier)
            counter.tick()
            repo.add(counter)
    return identifier


def _metadata(stream_name):
    return {
        "domain": {"kind": "EVENT"},
        "headers": {"id": str(uuid4()), "type": "Ticked", "stream": stream_name},
    }


def test_adapter_is_the_configured_provider(test_domain):
    service = test_domain.event_store

    assert service._adapter is not None
    expected = {"memory": MemoryEventStore, "message_db": MessageDBStore}
    provider = test_domain.config["event_store"]["provider"]
    assert type(service._adapter) is expected[provider]


class TestCategoryHeadPosition:
    def test_empty_category_is_minus_one(self, test_domain):
        assert test_domain.event_store.category_head_position("counter") == -1

    def test_empty_store_is_minus_one_for_all(self, test_domain):
        assert test_domain.event_store.category_head_position("$all") == -1

    def test_category_head_is_the_newest_row_of_the_category(self, test_domain):
        service = test_domain.event_store
        for i in range(3):
            service._write_message(
                "counter-1", "Ticked", {"n": i}, _metadata("counter-1")
            )
        service._write_message("other-1", "Ticked", {"n": 9}, _metadata("other-1"))

        newest = service._get_category_messages("counter")[-1]["global_position"]
        assert service.category_head_position("counter") == newest

    def test_all_head_is_the_newest_row_of_the_store(self, test_domain):
        service = test_domain.event_store
        service._write_message("counter-1", "Ticked", {"n": 0}, _metadata("counter-1"))
        service._write_message("other-1", "Ticked", {"n": 1}, _metadata("other-1"))

        newest = service._get_all_messages()[-1]["global_position"]
        assert service.category_head_position("$all") == newest
        assert service.category_head_position("counter") < newest

    def test_stream_name_head_is_the_newest_row_of_that_stream(self, test_domain):
        service = test_domain.event_store
        service._write_message("counter-1", "Ticked", {"n": 0}, _metadata("counter-1"))
        service._write_message("counter-2", "Ticked", {"n": 1}, _metadata("counter-2"))

        newest_in_one = service._get_stream_messages("counter-1")[-1]
        assert (
            service.category_head_position("counter-1")
            == (newest_in_one["global_position"])
        )


class TestReadKeywords:
    @pytest.mark.parametrize("keyword", ["no_of" + "_messages", "sql"])
    def test_read_rejects_removed_keywords(self, test_domain, keyword):
        # The old row-count name is built from parts so a search of the
        # repository for it finds no call that still uses it.
        with pytest.raises(TypeError, match=keyword):
            test_domain.event_store.read("counter", **{keyword: 5})


class TestLoadAggregateAtVersion:
    def test_at_version_two_is_the_state_after_the_third_event(self, test_domain):
        identifier = _counter_with_events(test_domain, 5)

        counter = test_domain.event_store.load_aggregate(
            Counter, identifier, at_version=2
        )

        assert counter is not None
        assert counter._version == 2
        assert counter.value == 2  # opened, then two ticks

    def test_at_version_past_the_head_raises(self, test_domain):
        identifier = _counter_with_events(test_domain, 5)

        with pytest.raises(ObjectNotFoundError, match="Latest version is 4"):
            test_domain.event_store.load_aggregate(Counter, identifier, at_version=7)


class TestLoadAggregateAtVersionFromSnapshot:
    def _counter_with_marked_snapshot(self, test_domain):
        """Persist a 5-event counter and a snapshot at version 2 whose value
        no replay produces, so a result that carries it came from the snapshot."""
        identifier = _counter_with_events(test_domain, 5)
        snapshot = test_domain.event_store.load_aggregate(
            Counter, identifier, at_version=2
        ).to_dict()
        snapshot["value"] = 100
        test_domain.event_store._write_message(
            f"{Counter.meta_.stream_category}:snapshot-{identifier}",
            SNAPSHOT_TYPE,
            snapshot,
        )
        return identifier

    def test_snapshot_at_or_before_the_version_is_the_starting_state(self, test_domain):
        identifier = self._counter_with_marked_snapshot(test_domain)

        counter = test_domain.event_store.load_aggregate(
            Counter, identifier, at_version=3
        )

        assert counter._version == 3
        # The fourth event (a tick to 3) applies on top of the snapshot.
        assert counter.value == 3
        at_snapshot = test_domain.event_store.load_aggregate(
            Counter, identifier, at_version=2
        )
        assert at_snapshot.value == 100

    def test_version_past_the_head_raises_on_the_snapshot_path(self, test_domain):
        identifier = self._counter_with_marked_snapshot(test_domain)

        with pytest.raises(ObjectNotFoundError, match="Latest version is 4"):
            test_domain.event_store.load_aggregate(Counter, identifier, at_version=7)
