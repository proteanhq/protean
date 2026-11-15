"""The domain's ``EventStore`` service against the configured store.

The service holds the adapter, answers ``category_head_position`` and loads
aggregates. The ``BaseEventStore`` methods that ``.store`` still exposes hand
their call to the service.
"""

from uuid import uuid4

import pytest

from protean.adapters.event_store.memory import MemoryEventStore
from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ObjectNotFoundError
from protean.fields import Identifier, Integer

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


def test_store_is_the_adapter(test_domain):
    service = test_domain.event_store

    assert service._adapter is not None
    assert service.store is service._adapter
    if test_domain.config["event_store"]["provider"] == "memory":
        assert isinstance(service._adapter, MemoryEventStore)


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


class TestStoreDelegates:
    def test_load_aggregate_reaches_the_service(self, test_domain, monkeypatch):
        calls = []

        def record(part_of, identifier, *, at_version=None, as_of=None):
            calls.append((part_of, identifier, at_version, as_of))
            return "loaded"

        monkeypatch.setattr(test_domain.event_store, "load_aggregate", record)

        result = test_domain.event_store.store.load_aggregate(
            Counter, "1", at_version=2
        )

        assert result == "loaded"
        assert calls == [(Counter, "1", 2, None)]

    def test_stream_head_position_reaches_category_head_position(
        self, test_domain, monkeypatch
    ):
        calls = []

        def record(category):
            calls.append(category)
            return 11

        monkeypatch.setattr(test_domain.event_store, "category_head_position", record)

        assert test_domain.event_store.store.stream_head_position("counter") == 11
        assert calls == ["counter"]


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

        with pytest.raises(ObjectNotFoundError):
            test_domain.event_store.load_aggregate(Counter, identifier, at_version=7)
