"""Tests for the is_fact_event meta option on BaseEvent.

Gap 1: Fact events are now detected via `meta_.is_fact_event` meta option
instead of `__name__.endswith("FactEvent")` name convention.
"""

import pytest

from protean.core.aggregate import BaseAggregate, element_to_fact_event
from protean.core.event import BaseEvent
from protean.fields import String


class University(BaseAggregate):
    name: String(max_length=50)


class UniversityRegistered(BaseEvent):
    name: String(max_length=50)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(University, fact_events=True)
    test_domain.register(UniversityRegistered, part_of=University)
    test_domain.init(traverse=False)


class TestIsFactEventMetaOption:
    def test_base_event_is_fact_event_defaults_to_false(self):
        """Normal events have meta_.is_fact_event = False."""
        assert UniversityRegistered.meta_.is_fact_event is False

    def test_generated_fact_event_has_is_fact_event_true(self, test_domain):
        """Fact events registered with the domain have meta_.is_fact_event = True."""
        registry = test_domain.registry
        event_records = registry._elements["EVENT"]
        fact_events = [r for r in event_records.values() if r.cls.meta_.is_fact_event]
        assert len(fact_events) >= 1

    def test_fact_event_is_subclass_of_base_event(self):
        fact_cls = element_to_fact_event(University)
        assert issubclass(fact_cls, BaseEvent)

    def test_fact_event_name_convention_preserved(self):
        """The generated class name still ends with FactEvent for readability."""
        fact_cls = element_to_fact_event(University)
        assert fact_cls.__name__ == "UniversityFactEvent"


class TestIsFactEventInEventSourcing:
    """Test that fact events behave correctly during ES aggregate operations."""

    def test_fact_event_on_persistence(self, test_domain):
        """Fact event is raised on persistence with meta_.is_fact_event = True."""
        user = University(name="MIT")
        test_domain.repository_for(University).add(user)

        # Read from fact event stream
        messages = test_domain.event_store.store.read(
            f"test::university-fact-{user.id}"
        )
        assert len(messages) == 1

        event = messages[0].to_domain_object()
        assert event.__class__.meta_.is_fact_event is True
        assert event.name == "MIT"


class TestIsFactEventInDomainValidation:
    """Test that is_fact_event is used during domain validation to skip
    fact events when checking for missing @apply handlers."""

    def test_fact_events_skipped_in_apply_handler_warning(self, test_domain):
        """Fact events should not trigger 'missing @apply handler' warnings."""
        registry = test_domain.registry
        event_records = registry._elements["EVENT"]
        fact_events = [r for r in event_records.values() if r.cls.meta_.is_fact_event]
        assert len(fact_events) >= 1
        assert all(r.cls.meta_.is_fact_event is True for r in fact_events)


class TestIsFactEventInVersionDetermination:
    """Test that is_fact_event is respected in Message._determine_expected_version."""

    def test_fact_event_expected_version_is_none(self, test_domain):
        """Fact events should return None for expected_version."""
        from protean.utils.eventing import Message

        user = University(name="MIT")
        test_domain.repository_for(University).add(user)

        messages = test_domain.event_store.store.read(
            f"test::university-fact-{user.id}"
        )
        event = messages[0].to_domain_object()

        # Fact events should return None for expected_version
        result = Message._determine_expected_version(event)
        assert result is None

    def test_regular_event_expected_version_is_set(self, test_domain):
        """Regular events should have expected_version set."""
        from protean.utils.eventing import Message

        user = University(name="MIT")
        user.raise_(UniversityRegistered(name="MIT"))
        test_domain.repository_for(University).add(user)

        messages = test_domain.event_store.store.read(f"test::university-{user.id}")
        # Find the non-fact event
        for msg in messages:
            event = msg.to_domain_object()
            if not event.__class__.meta_.is_fact_event:
                result = Message._determine_expected_version(event)
                assert result is not None
                break
